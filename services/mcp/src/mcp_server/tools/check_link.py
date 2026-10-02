"""check_link: is this store link alive? Plain logic, no MCP code.

A tool that fetches URLs is a security risk (SSRF): someone could pass an internal address and
make our server fetch it. So every request is guarded:
  1. https only, 2. host must be on the allow-list, 3. the host must resolve to PUBLIC addresses,
  4. redirects are followed by hand (max 3) and every hop goes through steps 1-3 again.

DNS rebinding: a hostile DNS server can answer "public address" to our check and "internal
address" a moment later when the HTTP client looks the name up again. So we look the name up ONCE,
check the answer, and connect to that exact IP address. The original hostname is still sent as the
Host header and for the TLS certificate check, so https stays verified.
"""

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urljoin, urlparse

import httpx
from fastmcp.exceptions import ToolError

from mcp_server.config import Settings
from mcp_server.schemas import LinkCheckResult

MAX_REDIRECTS = 3
BODY_BYTES = 30_000  # enough to read the page <title>; we never download whole pages
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
_NOT_FOUND_TITLE = re.compile(r"(page not found|404|no longer available|not found)", re.IGNORECASE)

Resolver = Callable[[str], Awaitable[list[str]]]


async def default_resolver(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def host_allowed(host: str, domains: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def all_public(addresses: list[str]) -> bool:
    """True only if every address is a normal public internet address."""
    if not addresses:
        return False
    for a in addresses:
        ip = ipaddress.ip_address(a)
        if not ip.is_global or ip.is_multicast:  # private, loopback, link-local, reserved...
            return False
    return True


async def _vet(url: str, cfg: Settings, resolver: Resolver) -> tuple[str | None, str | None]:
    """Decide whether the URL may be fetched. Returns (refusal reason, address to connect to);
    exactly one of the two is None."""
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        return "only https links are allowed", None
    if not host_allowed(parts.hostname, cfg.allowed_domains):
        return "this store is not on the allow-list", None
    try:
        addresses = await resolver(parts.hostname)
    except OSError:
        return "host could not be resolved", None
    if not all_public(addresses):
        return "address is not a public internet address", None
    return None, addresses[0]


def _pin(url: str, ip: str) -> str:
    """The same URL, but pointing at the already-checked IP address instead of the hostname."""
    parts = urlparse(url)
    host = f"[{ip}]" if ":" in ip else ip  # IPv6 literals need brackets
    netloc = host + (f":{parts.port}" if parts.port else "")
    return parts._replace(netloc=netloc).geturl()


def _result(url, final_url, verdict, reason, status=None) -> LinkCheckResult:
    return LinkCheckResult(
        url=url, final_url=final_url, verdict=verdict, reason=reason, status=status,
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def _classify(url: str, final_url: str, status: int, body: str) -> LinkCheckResult:
    if 200 < status < 300:
        # 202/204 and friends are not a real page. Amazon, for one, answers 202 with a bot challenge.
        return _result(url, final_url, "unverified", "bot_blocked", status)
    if status == 200:
        title = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        if title and _NOT_FOUND_TITLE.search(title.group(1)):
            return _result(url, final_url, "dead", "soft_404", status)  # 200 page saying "not found"
        return _result(url, final_url, "live", "ok", status)
    if status == 404:
        return _result(url, final_url, "dead", "not_found", status)
    if status == 410:
        return _result(url, final_url, "dead", "gone", status)
    if status >= 500:
        return _result(url, final_url, "unverified", "server_error", status)
    # 401/403/429...: the store is probably blocking automated checks. That is not "dead".
    return _result(url, final_url, "unverified", "bot_blocked", status)


async def run_check(
    url: str, cfg: Settings, client: httpx.AsyncClient, resolver: Resolver = default_resolver
) -> LinkCheckResult:
    refusal, ip = await _vet(url, cfg, resolver)
    if refusal or ip is None:  # a bad input: refuse loudly (the caller's mistake, not a dead link)
        raise ToolError(f"Link not allowed: {refusal}.")

    current = url
    for hop in range(MAX_REDIRECTS + 1):
        host = urlparse(current).hostname or ""
        try:
            async with client.stream(
                "GET",
                _pin(current, ip),  # connect to the address we checked, never look the name up again
                headers={"User-Agent": USER_AGENT, "Host": host},
                extensions={"sni_hostname": host},  # verify the TLS certificate against the real name
                follow_redirects=False,
            ) as resp:
                status, location = resp.status_code, resp.headers.get("location")
                chunks, size = [], 0
                async for chunk in resp.aiter_bytes():  # read only the first bytes
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= BODY_BYTES:
                        break
                body = b"".join(chunks).decode("utf-8", errors="ignore")
        except httpx.TimeoutException:
            return _result(url, current, "unverified", "timeout")
        except httpx.TransportError:
            return _result(url, current, "unverified", "connection_error")

        if 300 <= status < 400 and location:
            if hop == MAX_REDIRECTS:
                return _result(url, current, "unverified", "too_many_redirects", status)
            current = urljoin(current, location)
            refusal, next_ip = await _vet(current, cfg, resolver)  # every hop passes the same checks
            if refusal or next_ip is None:
                return _result(url, current, "unverified", "redirected_off_domain", status)
            ip = next_ip
            continue
        return _classify(url, current, status, body)
    return _result(url, current, "unverified", "too_many_redirects")  # unreachable; keeps types happy
