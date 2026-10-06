import pytest
from fastmcp import Client

from mcp_server.config import Settings
from mcp_server.providers.page_facts import PageFacts
from mcp_server.providers.tavily import Candidate, SearchOutcome
from mcp_server.server import build_server
from tests.fakes import FakePages, FakeTavily
from tests.keys import PUBLIC_PEM

CFG = Settings(tavily_api_key="x", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None)


async def _search_then_buy(provider, pages=None, index=0):
    server = build_server(CFG, provider=provider, page_reader=pages or FakePages())
    async with Client(server) as c:
        found = (await c.call_tool("search_products",
                 {"item": "polo t-shirt", "color": "blue", "max_price_inr": 99999})).structured_content
        product = found["results"][index]
        buy = await c.call_tool("get_buy_link", {"product_id": product["product_id"]})
        return product, buy.structured_content


async def test_buy_link_returns_the_stores_own_page_and_costs_no_search_credit(tavily_response):
    provider, pages = FakeTavily(tavily_response), FakePages()
    product, buy = await _search_then_buy(provider, pages)
    assert provider.calls == 1  # the search; the buy link made no provider call at all
    reads_after_search = len(pages.calls)
    assert buy["primary"]["store"] == product["retailer"] == "Blackberrys"
    assert buy["primary"]["url"] == product["url"] and buy["primary"]["url"].startswith("https://blackberrys.com/")
    assert buy["primary"]["domain_allowed"] is True and buy["primary"]["price_inr"] == product["price_inr"]
    assert len(pages.calls) == reads_after_search  # and read no page either


async def test_the_stock_the_page_stated_is_passed_on(tavily_response):
    from mcp_server.providers.tavily import parse_results

    first = parse_results(tavily_response, credits=1).candidates[0].url
    _, buy = await _search_then_buy(FakeTavily(tavily_response), FakePages({first: PageFacts(name="P", price_inr=900, in_stock=True)}))
    assert buy["primary"]["in_stock"] is True


async def test_unknown_product_id_gives_a_clear_expired_error(tavily_response):
    server = build_server(CFG, provider=FakeTavily(tavily_response), page_reader=FakePages())
    async with Client(server) as c:
        with pytest.raises(Exception, match="expired"):
            await c.call_tool("get_buy_link", {"product_id": "does-not-exist"})


class Shady:
    """A provider that (wrongly) hands back a page on a store we do not list."""

    credits_per_search = 1

    def __init__(self, url):
        self.url = url

    async def search(self, query, domains, context=None):
        return SearchOutcome([Candidate(self.url, "Blue Polo", "", 0.9, "Shady", "shady.example.com")], 1, 0, 1)


async def test_a_page_on_a_store_we_do_not_list_is_flagged_and_never_primary():
    _, buy = await _search_then_buy(Shady("https://shady.example.com/products/polo"))
    assert buy["primary"] is None and buy["offers"][0]["domain_allowed"] is False
    assert "NO_ALLOWED_STORE" in {w["code"] for w in buy["warnings"]}


async def test_http_links_on_approved_stores_are_upgraded_to_https():
    _, buy = await _search_then_buy(Shady("http://www.snitch.com/products/polo"))
    assert buy["primary"]["url"] == "https://www.snitch.com/products/polo"
    _, lookalike = await _search_then_buy(Shady("http://www.snitch.com.evil.example/products/polo"))
    assert lookalike["primary"] is None  # a look-alike host is neither upgraded nor offered
