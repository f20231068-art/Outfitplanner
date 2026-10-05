"""Reading a store's own product page: what it states (price, image, stock, colour), and the rules the fetch obeys."""

import json
from pathlib import Path

import httpx
import pytest

from mcp_server.config import Settings
from mcp_server.providers.page_facts import MAX_PAGE_BYTES, parse_facts, read_page

FIXTURES = Path(__file__).parent / "fixtures"
CFG = Settings(_env_file=None)


def page(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def ld(product: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps(product)}</script>'


# ---- real pages (captured 2026-10-05: only the JSON-LD and meta tags are kept) ----------------------------------------
def test_a_real_snitch_page_states_price_image_stock_and_colour():
    f = parse_facts(page("page_snitch.html"), "https://www.snitch.com/men-t-shirts/x/1")
    assert (f.name, f.price_inr, f.in_stock, f.color, f.material) == ("Soul Purple Oversized Fit T-Shirt", 831, True, "Purple", "Cotton")
    assert f.image_url.startswith("https://cdn.shopify.com/") and f.sources == ["json_ld"]


def test_real_veirdo_and_raymond_pages():
    veirdo = parse_facts(page("page_veirdo.html"), "https://veirdo.in/products/x")
    assert (veirdo.price_inr, veirdo.in_stock) == (549, True) and veirdo.image_url.startswith("https://veirdo.in/")
    raymond = parse_facts(page("page_raymond.html"), "https://myraymond.com/products/x")
    assert (raymond.price_inr, raymond.in_stock) == (797, True) and raymond.image_url.startswith("https://myraymond.com/")


def test_a_real_page_with_only_a_logo_in_its_meta_tags_gives_no_image_and_no_price():
    f = parse_facts(page("page_wrogn_og_only.html"), "https://wrogn.com/products/x")
    assert f.price_inr is None and f.image_url == "" and f.in_stock is None  # the og:image was the store's logo


# ---- the rules, on small pages ------------------------------------------------------------------------------------
BASE = "https://shop.example/products/x"


def facts_of(*blobs: str, base: str = BASE):
    return parse_facts("<html><head>" + "".join(blobs) + "</head></html>", base)


def test_variants_the_cheapest_buyable_price_wins_and_sold_out_only_if_every_variant_is():
    offers = [
        {"price": "999", "availability": "https://schema.org/OutOfStock"},
        {"price": "1,299.00", "availability": "https://schema.org/InStock"},
        {"price": "1499", "availability": "https://schema.org/InStock"},
    ]
    f = facts_of(ld({"@type": "Product", "name": "P", "offers": offers}))
    assert (f.price_inr, f.in_stock) == (1299, True)  # 999 is sold out, so it is not what a buyer pays
    f = facts_of(ld({"@type": "Product", "offers": [{"price": 500, "availability": "OutOfStock"}, {"price": 600, "availability": "SoldOut"}]}))
    assert f.in_stock is False


def test_an_aggregate_offer_and_a_graph_wrapper_are_understood():
    agg = {"@type": "Product", "offers": {"@type": "AggregateOffer", "offers": [{"price": 700, "availability": "InStock"}]}}
    assert facts_of(ld({"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, agg]})).price_inr == 700
    assert facts_of(ld({"@type": "Product", "offers": {"@type": "AggregateOffer", "lowPrice": "450"}})).price_inr == 450


def test_only_rupee_prices_are_taken():
    assert facts_of(ld({"@type": "Product", "offers": {"price": 29.99, "priceCurrency": "USD"}})).price_inr is None
    assert facts_of(ld({"@type": "Product", "offers": {"price": 2999, "priceCurrency": "INR"}})).price_inr == 2999
    assert facts_of(ld({"@type": "Product", "offers": {"priceSpecification": {"price": "1200", "priceCurrency": "INR"}}})).price_inr == 1200


def test_availability_words_and_an_unstated_availability():
    for word, expected in [("InStock", True), ("LimitedAvailability", True), ("OutOfStock", False), ("Discontinued", False),
                           ("PreOrder", None), ("", None)]:
        f = facts_of(ld({"@type": "Product", "offers": {"price": 500, "availability": f"https://schema.org/{word}"}}))
        assert f.in_stock is expected, word


def test_images_are_made_absolute_https_and_logos_are_never_a_product_photo():
    assert facts_of(ld({"@type": "Product", "image": ["/cdn/p1.jpg", "/cdn/p2.jpg"]})).image_url == "https://shop.example/cdn/p1.jpg"
    assert facts_of(ld({"@type": "Product", "image": "http://img.example/p.jpg"})).image_url == "https://img.example/p.jpg"
    assert facts_of(ld({"@type": "Product", "image": {"@type": "ImageObject", "url": "https://i.example/a.png"}})).image_url == "https://i.example/a.png"
    meta = '<meta property="og:image" content="https://shop.example/files/STORE-LOGO.png">'
    assert facts_of(meta).image_url == ""


def test_meta_tags_fill_in_what_json_ld_does_not_say():
    f = facts_of('<meta content="https://shop.example/files/p.jpg" property="og:image"><meta property="product:price:amount" content="1599.00"><meta property="product:price:currency" content="INR">')
    assert (f.price_inr, f.image_url, f.sources) == (1599, "https://shop.example/files/p.jpg", ["open_graph", "open_graph"])
    assert facts_of('<meta property="product:price:amount" content="19"><meta property="product:price:currency" content="USD">').price_inr is None


def test_broken_or_irrelevant_structured_data_never_raises():
    assert facts_of('<script type="application/ld+json">{not json</script>').price_inr is None
    assert facts_of(ld({"@type": "Organization", "name": "Store"})).price_inr is None
    assert facts_of("").name is None


# ---- the fetch: held to the same rules as check_link -----------------------------------------------------------------
def ok_page(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="<html><head>" + ld({"@type": "Product", "name": "Polo", "offers": {"price": 999, "availability": "InStock"}}) + "</head></html>")


async def public(host):
    return ["104.18.2.2"]


async def read(url, handler=ok_page, resolver=public):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await read_page(url, CFG, client, resolver)


async def test_a_page_is_read_by_connecting_to_the_address_that_was_checked():
    seen = {}

    def handler(request):
        seen["host_header"], seen["url"], seen["sni"] = request.headers["host"], str(request.url), request.extensions["sni_hostname"]
        return ok_page(request)

    facts = await read("https://www.snitch.com/products/polo", handler)
    assert facts.price_inr == 999 and facts.in_stock is True
    assert seen["url"].startswith("https://104.18.2.2/") and seen["host_header"] == "www.snitch.com"
    assert seen["sni"] == "www.snitch.com"  # the certificate is still checked against the real name


@pytest.mark.parametrize("url", [
    "http://www.snitch.com/products/polo",  # not https
    "https://evil.example.com/products/polo",  # not an approved store
    "https://snitch.com.evil.example/products/polo",  # a look-alike
    "https://www.amazon.in/dp/B0EXAMPLE",  # a store we no longer use
])
async def test_pages_that_are_not_https_on_an_approved_store_are_never_fetched(url):
    def never(request):
        pytest.fail("must not fetch")

    assert await read(url, never) is None


async def test_a_store_that_resolves_to_a_private_address_is_never_fetched():
    async def internal(host):
        return ["10.0.0.5"]

    def never(request):
        pytest.fail("must not fetch")

    assert await read("https://www.snitch.com/products/polo", never, internal) is None


async def test_a_redirect_off_the_approved_stores_is_not_followed():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.example.com/steal"})

    assert await read("https://www.snitch.com/products/polo", handler) is None


async def test_a_redirect_within_the_approved_stores_is_followed():
    def handler(request):
        if request.headers["host"] == "snitch.com":
            return httpx.Response(301, headers={"location": "https://www.snitch.com/products/polo"})
        return ok_page(request)

    assert (await read("https://snitch.com/products/polo", handler)).price_inr == 999


@pytest.mark.parametrize("status", [403, 404, 429, 500])
async def test_a_blocked_or_missing_page_is_unreadable_not_an_error(status):
    assert await read("https://www.snitch.com/products/polo", lambda r: httpx.Response(status)) is None


async def test_a_network_failure_is_unreadable_not_an_error():
    def boom(request):
        raise httpx.ConnectError("refused")

    assert await read("https://www.snitch.com/products/polo", boom) is None


async def test_only_the_first_part_of_a_huge_page_is_read():
    head = ld({"@type": "Product", "name": "Polo", "offers": {"price": 999}})
    big = "<html><head>" + head + "</head><body>" + ("x" * (MAX_PAGE_BYTES * 2)) + "</body></html>"
    facts = await read("https://www.snitch.com/products/polo", lambda r: httpx.Response(200, content=big.encode()))
    assert facts.price_inr == 999  # found near the top, long before the size limit


# ---- the page's own description ---------------------------------------------------------------------------------------
def test_the_description_is_plain_one_line_text_cut_at_a_word():
    from mcp_server.providers.page_facts import MAX_DETAILS_CHARS

    html = ld({"@type": "Product", "name": "Tee", "description": "<p>Soft   cotton</p>\n<ul><li>Off white &amp; boxy</li></ul>"})
    assert parse_facts(html, "https://x.example/p").details == "Soft cotton Off white & boxy"
    long = ld({"@type": "Product", "name": "Tee", "description": "word " * 400})
    details = parse_facts(long, "https://x.example/p").details
    assert len(details) <= MAX_DETAILS_CHARS + 3 and details.endswith("...")


def test_the_description_falls_back_to_the_meta_tag_and_is_empty_when_the_page_says_nothing():
    meta = '<meta property="og:description" content="Relaxed fit tee in white">'
    assert parse_facts(meta, "https://x.example/p").details == "Relaxed fit tee in white"
    assert parse_facts("<html></html>", "https://x.example/p").details == ""
