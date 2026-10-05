"""The server must be usable ONLY by our API, with a short-lived signed token (JWT, RS256).

Sections: (1) which tokens are accepted, (2) clocks that disagree, (3) a stolen token being
replayed, (4) the real HTTP server, (5) refusing to start without a key.
"""

import logging

import pytest
from starlette.testclient import TestClient

from mcp_server.auth import ReplayGuard, ServiceJWTVerifier, build_verifier
from mcp_server.config import Settings
from mcp_server.server import build_server, http_guard
from tests.keys import ATTACKER_PRIVATE_PEM, PUBLIC_PEM, mint

CFG = Settings(tavily_api_key="x", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None)


def verifier(**kw) -> ServiceJWTVerifier:
    args = {"issuer": "stylist-api", "audience": "stylist-mcp", "leeway_s": 10, "max_lifetime_s": 60, **kw}
    return ServiceJWTVerifier(PUBLIC_PEM, **args)


# ---- 1. which tokens are accepted ---------------------------------------------------------
async def test_a_valid_token_is_accepted_and_carries_the_user():
    result = await verifier().verify_token(mint("user_42"))
    assert result is not None and result.subject == "user_42" and result.client_id == "stylist-api"


@pytest.mark.parametrize(
    "label,token",
    [
        ("signed with someone else's key", mint(key=ATTACKER_PRIVATE_PEM)),
        ("meant for another service", mint(aud="some-other-service")),
        ("issued by someone else", mint(iss="evil-issuer")),
        ("no signature at all (alg none)", mint(algorithm="none")),
        ("no unique id", mint(drop=("jti",))),
        ("no expiry", mint(drop=("exp",))),
        ("no user", mint(drop=("sub",))),
        ("garbage", "not.a.token"),
        ("empty", ""),
    ],
)
async def test_bad_tokens_are_refused(label, token):
    assert await verifier().verify_token(token) is None, label


async def test_a_token_with_edited_payload_is_refused():
    head, _body, sig = mint("user_42").split(".")
    other_body = mint("admin").split(".")[1]  # a genuine payload, but not the one that was signed
    assert await verifier().verify_token(f"{head}.{other_body}.{sig}") is None


async def test_a_correctly_signed_token_claiming_a_long_life_is_refused():
    assert await verifier().verify_token(mint(ttl=3600)) is None  # lifetime cap is 60 s


# ---- 2. clocks that disagree (problem 1) --------------------------------------------------
async def test_a_small_clock_difference_is_tolerated():
    assert await verifier().verify_token(mint(skew=+8)) is not None  # API clock 8 s ahead
    assert await verifier().verify_token(mint(skew=-8, ttl=30)) is not None  # API clock 8 s behind


async def test_a_big_clock_difference_is_refused():
    assert await verifier().verify_token(mint(skew=+25)) is None  # 25 s ahead: beyond the 10 s leeway
    assert await verifier().verify_token(mint(skew=-45, ttl=30)) is None  # long expired


async def test_leeway_is_a_setting_and_zero_means_no_tolerance():
    assert await verifier(leeway_s=0).verify_token(mint(skew=+8)) is None
    assert await verifier(leeway_s=30).verify_token(mint(skew=+25)) is not None


async def test_leeway_only_forgives_small_differences_in_the_expiry_too():
    assert await verifier().verify_token(mint(skew=-33, ttl=30)) is not None  # expired 3 s ago: inside 10 s
    assert await verifier().verify_token(mint(skew=-45, ttl=30)) is None  # expired 15 s ago: outside it


async def test_a_timing_refusal_logs_how_many_seconds_off_the_token_was(caplog):
    with caplog.at_level(logging.WARNING, logger="mcp_server.auth"):
        await verifier().verify_token(mint(skew=+25))
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "iat +2" in text and "vs our clock" in text  # e.g. "iat +25s" : clock trouble is visible
    assert "eyJ" not in text  # the token itself is never written to the log


# ---- 3. a stolen token being replayed (problem 5) -----------------------------------------
async def test_a_token_works_once_and_a_second_use_is_refused():
    v, token = verifier(), mint()
    assert await v.verify_token(token) is not None  # the legitimate request
    assert await v.verify_token(token) is None  # a stolen copy replayed afterwards


async def test_every_fresh_token_is_accepted_even_for_the_same_user():
    v = verifier()
    for _ in range(5):
        assert await v.verify_token(mint("user_42")) is not None


async def test_replay_is_refused_even_though_the_token_has_not_expired():
    v, token = verifier(), mint(ttl=30)
    await v.verify_token(token)
    assert await v.verify_token(token) is None  # ~29 s of validity left, still refused


def test_used_ids_are_forgotten_once_they_could_no_longer_be_valid():
    now = [1000.0]
    guard = ReplayGuard(max_items=2, clock=lambda: now[0])
    assert guard.first_use("a", 1030) and guard.first_use("b", 1030)
    assert not guard.first_use("a", 1030)  # replay
    assert not guard.first_use("c", 1030)  # full of unexpired ids: fail closed, never grow forever
    now[0] = 1031  # everything remembered has expired
    assert guard.first_use("c", 1061)  # space is made again


# ---- 4. the real HTTP server --------------------------------------------------------------
INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}},
}
BASE = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def client():
    server = build_server(CFG, provider=object())
    with TestClient(server.http_app(**http_guard(CFG)), base_url="http://127.0.0.1:8001") as c:
        yield c


def post(client, token=None, host=None, origin=None, body=INIT):
    headers = dict(BASE)
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if host:
        headers["Host"] = host
    if origin:
        headers["Origin"] = origin
    return client.post("/mcp", json=body, headers=headers)


def test_no_token_is_refused(client):
    assert post(client).status_code == 401


def test_a_forged_token_is_refused(client):
    assert post(client, token=mint(key=ATTACKER_PRIVATE_PEM)).status_code == 401
    assert post(client, token="not-a-token").status_code == 401


def test_a_valid_token_is_accepted(client):
    r = post(client, token=mint())
    assert r.status_code == 200 and "stylist-tools" in r.text


def test_replaying_a_captured_token_over_http_fails(client):
    token = mint()
    assert post(client, token=token).status_code == 200  # the real request
    assert post(client, token=token).status_code == 401  # the thief's copy


def test_each_http_request_needs_its_own_fresh_token(client):
    first = post(client, token=mint())
    assert first.status_code == 200
    follow_up = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    sid = {"mcp-session-id": first.headers["mcp-session-id"]} if "mcp-session-id" in first.headers else {}
    r = client.post("/mcp", json=follow_up, headers={**BASE, **sid, "Authorization": f"Bearer {mint()}"})
    assert r.status_code == 200 and "search_products" in r.text


def test_tools_cannot_be_called_without_a_token(client):
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "ping", "arguments": {}}}
    r = post(client, body=body)
    assert r.status_code == 401 and "pong" not in r.text


def test_a_foreign_host_or_origin_is_refused_even_with_a_valid_token(client):
    assert post(client, token=mint(), host="evil.example.com").status_code in (400, 403, 421)
    assert post(client, token=mint(), origin="https://evil.example.com").status_code == 403


# ---- 5. refusing to start without a key ----------------------------------------------------
@pytest.mark.parametrize("bad", ["", "not a key", "-----BEGIN PUBLIC KEY-----\nbm9wZQ==\n-----END PUBLIC KEY-----"])
def test_server_refuses_to_start_without_a_usable_public_key(bad):
    with pytest.raises(RuntimeError, match="MCP_JWT_PUBLIC_KEY"):
        build_server(Settings(tavily_api_key="x", mcp_jwt_public_key=bad, _env_file=None), provider=object())


def test_a_key_stored_on_one_line_with_literal_backslash_n_still_loads():
    one_line = PUBLIC_PEM.strip().replace("\n", "\\n")  # how hosts store multi-line values
    assert build_verifier(Settings(mcp_jwt_public_key=one_line, _env_file=None)) is not None
