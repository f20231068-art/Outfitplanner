import httpx
import pytest
from fastmcp.exceptions import ToolError

from mcp_server.config import Settings
from mcp_server.tools.check_link import all_public, host_allowed, run_check

CFG = Settings(tavily_api_key="x", _env_file=None)
GOOD = "https://www.snitch.com/tshirts/x/1/buy"


async def public_resolver(host: str) -> list[str]:
    return ["104.18.2.2"]  # a normal public address


def client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def check(handler, url=GOOD, resolver=public_resolver):
    async with client_for(handler) as c:
        return await run_check(url, CFG, c, resolver)


# ---- the verdicts ------------------------------------------------------------------------
async def test_live_page():
    r = await check(lambda req: httpx.Response(200, text="<html><title>Cool T-shirt</title></html>"))
    assert (r.verdict, r.reason, r.status) == ("live", "ok", 200)


@pytest.mark.parametrize(
    "status,verdict,reason",
    [(404, "dead", "not_found"), (410, "dead", "gone"), (403, "unverified", "bot_blocked"),
     (429, "unverified", "bot_blocked"), (503, "unverified", "server_error")],
)
async def test_status_codes_map_to_verdicts(status, verdict, reason):
    r = await check(lambda req: httpx.Response(status))
    assert (r.verdict, r.reason) == (verdict, reason)


async def test_a_200_page_titled_not_found_is_dead():
    r = await check(lambda req: httpx.Response(200, text="<title>Page Not Found | Snitch</title>"))
    assert (r.verdict, r.reason) == ("dead", "soft_404")


async def test_timeout_is_unverified_not_dead():
    def boom(req):
        raise httpx.ConnectTimeout("slow")

    r = await check(boom)
    assert (r.verdict, r.reason) == ("unverified", "timeout")


# ---- redirects ---------------------------------------------------------------------------
async def test_follows_a_redirect_within_allowed_hosts():
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://www.snitch.com/new"})
        return httpx.Response(200, text="<title>ok</title>")

    r = await check(handler, url="https://www.snitch.com/old")
    assert r.verdict == "live" and r.final_url == "https://www.snitch.com/new"


async def test_redirect_to_a_host_we_do_not_allow_is_not_followed():
    hits = []

    def handler(req):
        hits.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    r = await check(handler)
    assert (r.verdict, r.reason) == ("unverified", "redirected_off_domain")
    assert len(hits) == 1 and "evil" not in hits[0]  # we never made a request to the evil host


async def test_redirect_loop_gives_up_after_three_hops():
    r = await check(lambda req: httpx.Response(302, headers={"location": "https://www.snitch.com/loop"}))
    assert r.reason == "too_many_redirects"


# ---- the security guards (SSRF) -----------------------------------------------------------
async def test_refuses_non_https():
    with pytest.raises(ToolError, match="https"):
        await check(lambda r: httpx.Response(200), url="http://www.snitch.com/x")


async def test_refuses_hosts_not_on_the_allow_list():
    with pytest.raises(ToolError, match="allow-list"):
        await check(lambda r: httpx.Response(200), url="https://evil.example.com/x")


async def test_refuses_an_allowed_name_that_resolves_to_a_private_address():
    async def internal(host):
        return ["10.0.0.5"]

    with pytest.raises(ToolError, match="public"):
        await check(lambda r: httpx.Response(200), resolver=internal)


async def test_refuses_when_any_resolved_address_is_internal():
    async def mixed(host):
        return ["104.18.2.2", "169.254.169.254"]  # one public, one cloud-metadata address

    with pytest.raises(ToolError):
        await check(lambda r: httpx.Response(200), resolver=mixed)


def test_address_classification():
    assert all_public(["8.8.8.8", "104.18.2.2"])
    for bad in ("127.0.0.1", "10.1.2.3", "192.168.0.1", "172.16.0.9", "169.254.169.254", "::1", "0.0.0.0"):
        assert not all_public([bad]), bad
    assert not all_public([])


def test_host_matching_cannot_be_fooled_by_lookalike_names():
    d = CFG.allowed_domains
    assert host_allowed("www.snitch.com", d) and host_allowed("snitch.com", d)
    assert not host_allowed("evil-snitch.com", d)
    assert not host_allowed("snitch.com.evil.com", d)
    assert not host_allowed("notsnitch.com", d)


# ---- DNS rebinding: look the name up once, then connect to exactly that address -----------------
async def test_the_connection_goes_to_the_checked_ip_with_the_real_name_for_host_and_tls():
    seen = {}

    def handler(req):
        seen.update(host_header=req.headers["host"], connected_to=req.url.host, sni=req.extensions.get("sni_hostname"))
        return httpx.Response(200, text="<title>ok</title>")

    await check(handler)
    assert seen["connected_to"] == "104.18.2.2"  # the address we verified, not a fresh lookup
    assert seen["host_header"] == "www.snitch.com"
    assert seen["sni"] == "www.snitch.com"  # the TLS certificate is still checked against the real name


async def test_a_hostile_dns_that_changes_its_answer_cannot_redirect_us_to_an_internal_address():
    answers = [["104.18.2.2"], ["10.0.0.5"]]  # first lookup: public. Any second lookup: internal.
    lookups = []

    async def rebinding_resolver(host):
        lookups.append(host)
        return answers[min(len(lookups) - 1, 1)]

    connected = []

    def handler(req):
        connected.append(req.url.host)
        return httpx.Response(200, text="<title>ok</title>")

    r = await check(handler, resolver=rebinding_resolver)
    assert r.verdict == "live"
    assert connected == ["104.18.2.2"]  # never the internal address
    assert len(lookups) == 1  # the name was looked up once, not again at connection time


async def test_each_redirect_hop_is_looked_up_and_checked_again():
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(301, headers={"location": "https://www.snitch.com/new"})
        return httpx.Response(200, text="<title>ok</title>")

    async def second_hop_internal(host, _calls=[]):  # noqa: B006 - small test-only counter
        _calls.append(1)
        return ["104.18.2.2"] if len(_calls) == 1 else ["192.168.1.10"]

    r = await check(handler, url="https://www.snitch.com/old", resolver=second_hop_internal)
    assert (r.verdict, r.reason) == ("unverified", "redirected_off_domain")


def test_pinning_builds_the_right_url_for_ipv4_ipv6_and_ports():
    from mcp_server.tools.check_link import _pin

    assert _pin("https://www.snitch.com/a/b?x=1", "104.18.2.2") == "https://104.18.2.2/a/b?x=1"
    assert _pin("https://www.snitch.com:8443/a", "104.18.2.2") == "https://104.18.2.2:8443/a"
    assert _pin("https://www.snitch.com/a", "2606:4700::1") == "https://[2606:4700::1]/a"


@pytest.mark.parametrize("status", [202, 204])
async def test_a_2xx_that_is_not_200_is_not_proof_the_page_is_live(status):
    r = await check(lambda req: httpx.Response(status, text="challenge"))
    assert (r.verdict, r.reason) == ("unverified", "bot_blocked")
