"""Limits cap the damage when something else fails: floods, runaway loops, a stolen token."""

import json
from datetime import UTC, datetime

import pytest
from fastmcp import Client
from starlette.testclient import TestClient

from mcp_server.config import Settings
from mcp_server.limits import CreditLedger, LimitExceeded, RateLimiter
from mcp_server.server import assert_safe_bind, build_server, http_guard
from tests.fakes import FakePages, FakeTavily
from tests.keys import PUBLIC_PEM, mint


def cfg(**kw) -> Settings:
    return Settings(tavily_api_key="x", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None, **kw)


# ---- the rate limiter ---------------------------------------------------------------------
def test_a_user_is_refused_after_too_many_calls_in_a_minute_and_told_when_to_retry():
    now = [1000.0]
    limiter = RateLimiter(3, clock=lambda: now[0])
    for _ in range(3):
        limiter.check("u")
    with pytest.raises(LimitExceeded) as exc:
        limiter.check("u")
    assert 1 <= exc.value.retry_after_s <= 61 and "seconds" in str(exc.value)


def test_the_window_slides_so_old_calls_stop_counting():
    now = [1000.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    limiter.check("u")
    limiter.check("u")
    now[0] += 61
    limiter.check("u")  # the earlier calls are over a minute old


def test_one_users_flood_does_not_affect_another_user():
    limiter = RateLimiter(1)
    limiter.check("alice")
    with pytest.raises(LimitExceeded):
        limiter.check("alice")
    limiter.check("bob")  # unaffected


# ---- the credit ledger --------------------------------------------------------------------
def test_a_user_cannot_spend_more_than_their_daily_allowance():
    ledger = CreditLedger(per_user_daily=2, global_daily=100)
    ledger.spend("u")
    ledger.spend("u")
    with pytest.raises(LimitExceeded, match="allowance"):
        ledger.spend("u")


def test_the_whole_service_has_a_daily_cap_too():
    ledger = CreditLedger(per_user_daily=100, global_daily=3)
    for user in ("a", "b", "c"):
        ledger.spend(user)
    with pytest.raises(LimitExceeded, match="whole service"):
        ledger.spend("d")  # a fresh user, but the service-wide budget is gone


def test_a_refused_spend_is_not_counted():
    ledger = CreditLedger(per_user_daily=1, global_daily=100)
    ledger.spend("u")
    for _ in range(5):
        with pytest.raises(LimitExceeded):
            ledger.spend("u")
    assert ledger.used_today == 1


def test_allowances_reset_at_midnight_utc():
    at = [datetime(2026, 10, 2, 23, 59, 30, tzinfo=UTC).timestamp()]
    ledger = CreditLedger(per_user_daily=1, global_daily=1, clock=lambda: at[0])
    ledger.spend("u")
    with pytest.raises(LimitExceeded) as exc:
        ledger.spend("u")
    assert exc.value.retry_after_s <= 30  # told when it resets
    at[0] += 60  # now just after midnight
    ledger.spend("u")
    assert ledger.used_today == 1


# ---- wired into the real tools ------------------------------------------------------------
async def test_too_many_tool_calls_in_a_minute_are_refused():
    server = build_server(cfg(mcp_rate_limit_per_min=3), provider=object())
    async with Client(server) as c:
        for _ in range(3):
            await c.call_tool("ping", {})
        with pytest.raises(Exception, match="Too many requests"):
            await c.call_tool("ping", {})


async def test_paid_searches_stop_at_the_daily_allowance_but_cached_ones_are_free(tavily_response):
    provider = FakeTavily(tavily_response)
    server = build_server(cfg(mcp_daily_credits_per_user=2), provider=provider, page_reader=FakePages())
    args = {"max_price_inr": 99999}
    async with Client(server) as c:
        await c.call_tool("search_products", {"item": "polo", "color": "blue", **args})
        await c.call_tool("search_products", {"item": "polo", "color": "blue", **args})  # cached: free
        await c.call_tool("search_products", {"item": "polo", "color": "black", **args})
        with pytest.raises(Exception, match="allowance"):
            await c.call_tool("search_products", {"item": "polo", "color": "navy", **args})
    assert provider.calls == 2  # only the two paid calls reached the provider


async def test_the_refused_search_never_reaches_the_provider(tavily_response):
    provider = FakeTavily(tavily_response)
    server = build_server(cfg(mcp_daily_credits_global=1), provider=provider, page_reader=FakePages())
    async with Client(server) as c:
        await c.call_tool("search_products", {"item": "chinos", "color": "beige", "max_price_inr": 5000})
        with pytest.raises(Exception, match="whole service"):
            await c.call_tool("search_products", {"item": "polo", "color": "white", "max_price_inr": 5000})
    assert provider.calls == 1


# ---- per-user limits use the user id from the verified token ------------------------------
def test_limits_are_tracked_per_user_over_real_http():
    server = build_server(cfg(mcp_rate_limit_per_min=2), provider=object())
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}

    with TestClient(server.http_app(**http_guard(cfg())), base_url="http://127.0.0.1:8001") as client:
        def ping(user: str) -> str:
            opened = client.post("/mcp", json=init, headers={**hdr, "Authorization": f"Bearer {mint(user)}"})
            sid = {"mcp-session-id": opened.headers["mcp-session-id"]}
            body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "ping", "arguments": {}}}
            r = client.post("/mcp", json=body, headers={**hdr, **sid, "Authorization": f"Bearer {mint(user)}"})
            text = r.text.split("data:", 1)[-1].strip() if "data:" in r.text else r.text
            return json.dumps(json.loads(text)["result"])

        assert "pong" in ping("alice") and "pong" in ping("alice")
        assert "Too many requests" in ping("alice")  # alice's 3rd call in the minute
        assert "pong" in ping("bob")  # bob is unaffected


# ---- health route and safe binding ---------------------------------------------------------
def test_health_route_needs_no_login_and_reveals_nothing_but_ok():
    server = build_server(cfg(), provider=object())
    with TestClient(server.http_app(**http_guard(cfg())), base_url="http://127.0.0.1:8001") as client:
        r = client.get("/health")
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert client.post("/mcp", json={}).status_code == 401  # the real endpoint is still locked


def test_the_server_refuses_to_listen_beyond_this_machine_without_an_allowed_host():
    with pytest.raises(RuntimeError, match="MCP_ALLOWED_HOSTS"):
        assert_safe_bind(cfg(mcp_host="0.0.0.0"))
    assert_safe_bind(cfg(mcp_host="0.0.0.0", mcp_allowed_hosts="mcp.internal"))  # fine with a name set
    assert_safe_bind(cfg())  # loopback is always fine


def test_zero_means_no_limit():
    """0 switches a limit off: the service then serves for as long as the provider does."""
    limiter = RateLimiter(0)
    for _ in range(1000):
        limiter.check("user_1")
    ledger = CreditLedger(0, 0)
    for _ in range(1000):
        ledger.spend("user_1")
    assert ledger.used_today == 1000  # still counted (for the metrics), just never refused


def test_each_cap_can_be_switched_off_on_its_own():
    only_global = CreditLedger(0, 3)
    for _ in range(3):
        only_global.spend("user_1")
    with pytest.raises(LimitExceeded):
        only_global.spend("user_2")
    only_user = CreditLedger(2, 0)
    only_user.spend("user_1", 2)
    with pytest.raises(LimitExceeded):
        only_user.spend("user_1")
    only_user.spend("user_2", 2)  # someone else is unaffected, and there is no global cap
