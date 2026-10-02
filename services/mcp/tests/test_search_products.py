import httpx
import pytest
from fastmcp import Client

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.net import UpstreamError, get_json
from mcp_server.providers.serpapi import SerpApiShopping, parse_shopping_results
from mcp_server.server import build_server
from mcp_server.tools.search_products import build_query, run_search
from tests.keys import PUBLIC_PEM

CFG = Settings(serpapi_api_key="test-key", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None)


class FakeProvider:
    """Stands in for SerpAPI: returns the real fixture, counts how often it is called."""

    def __init__(self, response: dict):
        self.response, self.calls = response, 0

    async def search(self, query: str):
        self.calls += 1
        return parse_shopping_results(self.response)


def _run(provider, cache=None, **kw):
    args = {"item": "chinos", "color": "beige", "max_price_inr": 5000, **kw}
    return run_search(provider, cache or TTLCache(60), TTLCache(60), CFG, **args)


# ---- parsing real data -------------------------------------------------------------------
def test_parse_real_response_gives_clean_typed_products(chinos_response):
    parsed, skipped = parse_shopping_results(chinos_response)
    assert len(parsed) + skipped == 14
    first = parsed[0].product
    assert isinstance(first.price_inr, int) and first.price_inr > 0
    assert first.url.startswith("http") and first.retailer
    assert first.url_kind == "google_product_page"  # search results have no direct store link
    assert all(p.product.image_url for p in parsed)


def test_discounted_items_get_the_list_price(chinos_response):
    parsed, _ = parse_shopping_results(chinos_response)
    discounted = [p.product for p in parsed if p.product.mrp_inr]
    assert discounted, "fixture should contain at least one discounted product"
    assert all(p.mrp_inr > p.price_inr for p in discounted)


# ---- query building ----------------------------------------------------------------------
def test_query_always_says_men_and_drops_repeated_words():
    assert build_query("oversized t-shirt", "black", "oversized", "cotton") == "men black oversized cotton t-shirt"
    assert build_query("chinos", "beige").startswith("men beige")


# ---- the tool's behaviour ----------------------------------------------------------------
async def test_unknown_retailers_are_dropped_with_a_warning(chinos_response):
    out = await _run(FakeProvider(chinos_response))
    assert out.results
    assert all(any(a in r.retailer.lower() for a in CFG.allowed_retailers) for r in out.results)
    assert "RETAILER_NOT_ALLOWED" in {w.code for w in out.warnings}


async def test_price_cap_filters_and_limit_truncates(chinos_response):
    cheap = await _run(FakeProvider(chinos_response), max_price_inr=900)
    assert all(r.price_inr <= 900 for r in cheap.results)
    assert "PRICE_OVER_CAP" in {w.code for w in cheap.warnings}
    two = await _run(FakeProvider(chinos_response), limit=2)
    assert len(two.results) == 2


async def test_second_identical_search_is_served_from_cache(chinos_response):
    provider, cache = FakeProvider(chinos_response), TTLCache(60)
    first = await _run(provider, cache)
    second = await _run(provider, cache)
    assert provider.calls == 1  # the credit was spent once
    assert (first.from_cache, second.from_cache) == (False, True)
    assert first.results == second.results


# ---- outbound HTTP: retries ---------------------------------------------------------------
async def test_retries_a_429_then_succeeds():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(1)
        return httpx.Response(429) if len(seen) == 1 else httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await get_json(client, "https://x.test", {}, base_delay=0) == {"ok": True}
    assert len(seen) == 2


async def test_bad_key_fails_immediately_without_retrying():
    seen = []

    def handler(request):
        seen.append(1)
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpstreamError) as exc:
            await get_json(client, "https://x.test", {}, base_delay=0)
    assert len(seen) == 1 and exc.value.retryable is False


async def test_gives_up_after_the_retries_and_says_it_is_retryable():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        with pytest.raises(UpstreamError) as exc:
            await get_json(client, "https://x.test", {}, retries=2, base_delay=0)
    assert exc.value.retryable is True


async def test_provider_without_a_key_refuses_to_call_out():
    provider = SerpApiShopping(Settings(serpapi_api_key="", _env_file=None), client=None)
    with pytest.raises(UpstreamError, match="SERPAPI_API_KEY"):
        await provider.search("men beige chinos")


# ---- through a real MCP client ------------------------------------------------------------
async def test_tool_is_discoverable_and_callable_through_mcp(chinos_response):
    server = build_server(CFG, provider=FakeProvider(chinos_response))
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert {"ping", "search_products"} <= set(tools)

        schema = tools["search_products"].input_schema
        assert set(schema["required"]) == {"item", "color", "max_price_inr"}  # optional ones are not required
        assert "description" in schema["properties"]["color"]

        result = await client.call_tool(
            "search_products", {"item": "chinos", "color": "beige", "max_price_inr": 5000, "limit": 3}
        )
        data = result.structured_content
        assert data["query_used"] == "men beige chinos" and len(data["results"]) == 3
        assert data["results"][0]["price_inr"] > 0 and data["schema_version"] == "1"


async def test_invalid_arguments_are_rejected_by_the_schema_before_our_code_runs(chinos_response):
    server = build_server(CFG, provider=FakeProvider(chinos_response))
    async with Client(server) as client:
        with pytest.raises(Exception):  # noqa: B017 - any MCP error is fine, it must not return data
            await client.call_tool("search_products", {"item": "chinos", "color": "beige", "max_price_inr": -5})


async def test_provider_outage_becomes_a_clean_tool_error():
    class Down:
        async def search(self, query):
            raise UpstreamError("search provider unavailable after 3 tries (HTTP 503)", retryable=True)

    server = build_server(CFG, provider=Down())
    async with Client(server) as client:
        with pytest.raises(Exception, match="You can retry"):
            await client.call_tool("search_products", {"item": "chinos", "color": "beige", "max_price_inr": 5000})
