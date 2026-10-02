"""The tool server's metrics: counted correctly, guarded by a token, and free of anything sensitive."""

import pytest
from fastmcp import Client
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

from mcp_server.auth import ServiceJWTVerifier
from mcp_server.config import Settings
from mcp_server.providers.serpapi import parse_shopping_results
from mcp_server.server import build_server, http_guard
from tests.keys import ATTACKER_PRIVATE_PEM, PUBLIC_PEM, mint


def cfg(**kw) -> Settings:
    return Settings(serpapi_api_key="x", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None, **kw)


def value(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class Provider:
    def __init__(self, response):
        self.response = response

    async def search(self, query):
        return parse_shopping_results(self.response)

    async def offers(self, ref):
        return []


# ---- the endpoint ------------------------------------------------------------------------------------
def test_metrics_are_off_unless_a_token_is_configured():
    server = build_server(cfg(), provider=object())
    with TestClient(server.http_app(**http_guard(cfg())), base_url="http://127.0.0.1:8001") as c:
        assert c.get("/metrics").status_code == 404


def test_metrics_need_the_exact_token_and_no_login_token_works_instead():
    config = cfg(metrics_token="scrape-secret-1")
    server = build_server(config, provider=object())
    with TestClient(server.http_app(**http_guard(config)), base_url="http://127.0.0.1:8001") as c:
        assert c.get("/metrics").status_code == 401
        assert c.get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/metrics", headers={"Authorization": f"Bearer {mint()}"}).status_code == 401  # a service token is not it
        ok = c.get("/metrics", headers={"Authorization": "Bearer scrape-secret-1"})
        assert ok.status_code == 200 and "mcp_tool_calls_total" in ok.text


# ---- what gets counted --------------------------------------------------------------------------------
async def test_tool_calls_are_counted_by_outcome_and_timed(chinos_response):
    server = build_server(cfg(), provider=Provider(chinos_response))
    ok_before = value("mcp_tool_calls_total", tool="search_products", outcome="ok")
    refused_before = value("mcp_tool_calls_total", tool="get_buy_link", outcome="refused")
    seconds_before = value("mcp_tool_seconds_count", tool="search_products")
    async with Client(server) as c:
        await c.call_tool("search_products", {"item": "chinos", "color": "beige", "max_price_inr": 5000})
        with pytest.raises(Exception, match="expired"):
            await c.call_tool("get_buy_link", {"product_id": "unknown"})
    assert value("mcp_tool_calls_total", tool="search_products", outcome="ok") == ok_before + 1
    assert value("mcp_tool_calls_total", tool="get_buy_link", outcome="refused") == refused_before + 1
    assert value("mcp_tool_seconds_count", tool="search_products") == seconds_before + 1


async def test_cache_hits_and_paid_credits_are_counted_separately(chinos_response):
    server = build_server(cfg(), provider=Provider(chinos_response))
    args = {"item": "polo", "color": "white", "max_price_inr": 5000}
    hit, miss, credits = (value("mcp_cache_total", tool="search_products", result="hit"),
                          value("mcp_cache_total", tool="search_products", result="miss"),
                          value("mcp_search_credits_spent_total", kind="search"))
    async with Client(server) as c:
        await c.call_tool("search_products", args)
        await c.call_tool("search_products", args)  # served from cache
    assert value("mcp_cache_total", tool="search_products", result="miss") == miss + 1
    assert value("mcp_cache_total", tool="search_products", result="hit") == hit + 1
    assert value("mcp_search_credits_spent_total", kind="search") == credits + 1  # the hit cost nothing


async def test_limit_hits_are_counted(chinos_response):
    server = build_server(cfg(mcp_daily_credits_per_user=1, mcp_rate_limit_per_min=2), provider=Provider(chinos_response))
    credit_before = value("mcp_limit_hits_total", limit="daily_credits")
    rate_before = value("mcp_limit_hits_total", limit="rate")
    async with Client(server) as c:
        await c.call_tool("search_products", {"item": "a", "color": "b", "max_price_inr": 5})
        with pytest.raises(Exception, match="allowance"):
            await c.call_tool("search_products", {"item": "c", "color": "d", "max_price_inr": 5})
        with pytest.raises(Exception, match="Too many"):
            await c.call_tool("ping", {})
    assert value("mcp_limit_hits_total", limit="daily_credits") == credit_before + 1
    assert value("mcp_limit_hits_total", limit="rate") == rate_before + 1


async def test_refusals_at_the_door_are_counted_by_reason():
    verifier = ServiceJWTVerifier(PUBLIC_PEM, "stylist-api", "stylist-mcp", leeway_s=10)
    forged = value("mcp_auth_refusals_total", reason="invalid_token")
    replay = value("mcp_auth_refusals_total", reason="replay")
    late = value("mcp_auth_refusals_total", reason="clock_or_expiry")
    await verifier.verify_token(mint(key=ATTACKER_PRIVATE_PEM))
    token = mint()
    await verifier.verify_token(token)
    await verifier.verify_token(token)
    await verifier.verify_token(mint(skew=-120))
    assert value("mcp_auth_refusals_total", reason="invalid_token") == forged + 1
    assert value("mcp_auth_refusals_total", reason="replay") == replay + 1
    assert value("mcp_auth_refusals_total", reason="clock_or_expiry") == late + 1


async def test_the_metrics_text_holds_no_user_ids_arguments_or_product_data(chinos_response):
    config = cfg(metrics_token="scrape-secret-2")
    server = build_server(config, provider=Provider(chinos_response))
    async with Client(server) as c:
        await c.call_tool("search_products", {"item": "very-secret-garment", "color": "hidden-colour", "max_price_inr": 5000})
    with TestClient(server.http_app(**http_guard(config)), base_url="http://127.0.0.1:8001") as c:
        text = c.get("/metrics", headers={"Authorization": "Bearer scrape-secret-2"}).text
    for forbidden in ("very-secret-garment", "hidden-colour", "user_42", "anonymous", "Myntra", "myntra.com"):
        assert forbidden not in text, forbidden
