import json
from pathlib import Path

import pytest
from fastmcp import Client

from mcp_server.config import Settings
from mcp_server.providers.serpapi import DetailRef, parse_offers, parse_shopping_results
from mcp_server.schemas import StoreOffer
from mcp_server.server import build_server
from tests.keys import PUBLIC_PEM

CFG = Settings(serpapi_api_key="x", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None)
OFFERS = json.loads((Path(__file__).parent / "fixtures" / "serpapi_offers.json").read_text(encoding="utf-8"))


class FakeProvider:
    def __init__(self, search_response, offers_response):
        self.search_response, self.offers_response = search_response, offers_response
        self.search_calls = self.offer_calls = 0

    async def search(self, query):
        self.search_calls += 1
        parsed, skipped = parse_shopping_results(self.search_response)
        for p in parsed:  # the real response has one Myntra item; point every ref at that store
            p.detail_ref = DetailRef("https://detail.test/x?token=1", p.product.title, p.product.retailer)
        return parsed, skipped

    async def offers(self, ref):
        self.offer_calls += 1
        return parse_offers(self.offers_response)


def test_parse_offers_reads_real_store_data():
    offers = parse_offers(OFFERS)
    assert offers and offers[0].store == "Myntra"
    assert offers[0].price_inr == 1499
    assert offers[0].in_stock is True  # "In stock online" in the listing
    assert offers[0].url.startswith("http")


async def _search_then_buy(provider, product_index=0):
    server = build_server(CFG, provider=provider)
    async with Client(server) as c:
        found = (await c.call_tool("search_products",
                 {"item": "chinos", "color": "beige", "max_price_inr": 99999})).structured_content
        product = found["results"][product_index]
        buy = await c.call_tool("get_buy_link", {"product_id": product["product_id"]})
        again = await c.call_tool("get_buy_link", {"product_id": product["product_id"]})
        return product, buy.structured_content, again.structured_content


async def test_buy_link_returns_the_stores_own_https_page_and_is_cached(chinos_response):
    provider = FakeProvider(chinos_response, OFFERS)
    # pick a Myntra product so the offer's store matches the listing
    server_results = parse_shopping_results(chinos_response)[0]
    idx = next(i for i, p in enumerate(server_results) if p.product.retailer == "Myntra")
    _product, buy, again = await _search_then_buy(provider, idx)

    assert buy["primary"]["store"] == "Myntra"
    assert buy["primary"]["url"].startswith("https://www.myntra.com/")  # http was upgraded
    assert buy["primary"]["domain_allowed"] is True and buy["from_cache"] is False
    assert again["from_cache"] is True
    assert provider.offer_calls == 1  # the second call spent no credit


async def test_unknown_product_id_gives_a_clear_expired_error(chinos_response):
    server = build_server(CFG, provider=FakeProvider(chinos_response, OFFERS))
    async with Client(server) as c:
        with pytest.raises(Exception, match="expired"):
            await c.call_tool("get_buy_link", {"product_id": "does-not-exist"})


async def test_offers_from_stores_we_do_not_show_are_flagged_and_never_primary(chinos_response):
    class Shady(FakeProvider):
        async def offers(self, ref):
            return [StoreOffer(store="ShadyShop", url="https://shady.example.com/p", domain_allowed=False)]

    _, buy, _ = await _search_then_buy(Shady(chinos_response, OFFERS))
    assert buy["primary"] is None
    assert buy["offers"][0]["domain_allowed"] is False
    assert "NO_ALLOWED_STORE" in {w["code"] for w in buy["warnings"]}
