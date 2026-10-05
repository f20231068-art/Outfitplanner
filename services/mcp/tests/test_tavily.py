"""The Tavily adapter: finding candidate product pages in the approved stores, and the request it sends."""

import json

import httpx
import pytest

from mcp_server.config import Settings
from mcp_server.net import UpstreamError
from mcp_server.providers.tavily import (
    TavilySearch,
    clean_title,
    good_product_name,
    looks_like_product_page,
    parse_results,
    product_id_for,
    tidy_title,
)
from mcp_server.sellers import ALL_DOMAINS, GROUPS, SELLERS, domains_for, seller_for_host


# ---- the seller list --------------------------------------------------------------------------------------------
def test_the_seller_list_matches_the_file_it_was_generated_from():
    assert len(SELLERS) == 100 and len({s.domain for s in SELLERS}) == 100
    counts = {g: sum(s.group == g for s in SELLERS) for g in GROUPS}
    assert counts == {"streetwear": 30, "smart_casual": 31, "denim": 7, "traditional": 23, "activewear": 9}
    assert "abfrl.in" in ALL_DOMAINS  # the target several listed stores redirect to
    for gone in ("myntra.com", "amazon.in", "ajio.com", "flipkart.com", "tatacliq.com", "nykaa.com"):
        assert gone not in ALL_DOMAINS


def test_groups_pick_their_own_stores_and_hosts_match_only_whole_domains():
    streetwear = domains_for(["streetwear"])
    assert len(streetwear) == 30 and "snitch.com" in streetwear and "spykar.com" not in streetwear
    assert domains_for(None) == domains_for(GROUPS) and len(domains_for(None)) == 100
    assert seller_for_host("www.snitch.com").brand == "Snitch"
    assert seller_for_host("in.puma.com").brand == "Puma India"
    assert seller_for_host("evil-snitch.com") is None and seller_for_host("snitch.com.evil.com") is None


# ---- page type, titles --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("url,expected", [
    ("https://www.snitch.com/products/blue-polo", True),
    ("https://www.wrogn.com/collections/polos/products/navy-polo", True),  # a product inside a collection URL
    ("https://www.bewakoof.com/p/men-blue-polo", True),
    ("https://www.thesouledstore.com/product/blue-polo", True),
    ("https://www.snitch.com/men-t-shirts/blue-knitted-polo-t-shirt-4mst2346-03/8468306296994/buy", True),  # real Snitch address
    ("https://www.beyoung.in/teal-blue-check-jacquard-textured-polo-t-shirt", True),  # real Beyoung address: no /products/
    ("https://www.snitch.com/men-t-shirts", False),  # a category
    ("https://www.snitch.com/collections/polos", False),
    ("https://www.montecarlo.in/collections/polo-t-shirts-for-men", False),
    ("https://www.marksandspencer.in/l/men/t-shirts-and-polos", False),
    ("https://gant.in/blogs/news/right-fit-in-shirt-for-men", False),
    ("https://www.levi.in/search?q=polo", False),
    ("https://www.dennislingo.com/", False),
    ("https://www.dennislingo.com", False),
])
def test_looks_like_product_page(url, expected):
    assert looks_like_product_page(url) is expected


def test_clean_title_removes_the_stores_name_suffix_only():
    assert clean_title("Blue Polo T-Shirt | SNITCH", "Snitch", "snitch.com") == "Blue Polo T-Shirt"
    assert clean_title("Men Polo T-Shirt – Nobero", "Nobero", "nobero.com") == "Men Polo T-Shirt"
    assert clean_title("Buy Light Blue Textured Polo T-Shirt for Men at Blackberrys", "Blackberrys", "blackberrys.com").startswith("Buy Light Blue")
    assert clean_title("Blue Polo - Slim Fit", "Snitch", "snitch.com") == "Blue Polo - Slim Fit"  # not a store suffix
    assert clean_title("SNITCH", "Snitch", "snitch.com") == "SNITCH"  # never empties the title


@pytest.mark.parametrize("raw,expected", [
    ("Buy Light Blue Textured Polo T-Shirt for Men at Blackberrys", "Light Blue Textured Polo T-Shirt for Men"),
    ("Buy Cosmispire black oversized t shirt for men online in India", "Cosmispire black oversized t shirt for men"),
    ("Shop Gant Men Navy Blue Solid Regular Fit Polo T-Shirt", "Gant Men Navy Blue Solid Regular Fit Polo T-Shirt"),
    ("Park Avenue Men Blue Slim Fit Printed Polo", "Park Avenue Men Blue Slim Fit Printed Polo"),
    ("Online", "Online"),  # never empties the title
])
def test_tidy_title_makes_a_page_title_read_like_a_product_name(raw, expected):
    assert tidy_title(raw) == expected


@pytest.mark.parametrize("name,ok", [
    ("Soul Purple Oversized Fit T-Shirt", True), ("Default Title", False), ("30", False), ("XL", False),
    ("", False), (None, False), ("Title", False), ("Chinos", True),
])
def test_junk_product_names_are_recognised(name, ok):
    assert good_product_name(name) is ok


# ---- the whole response (REAL Tavily responses captured 2026-10-05) --------------------------------------------------
def test_a_real_polo_search_gives_candidates_from_approved_stores_best_first(tavily_response):
    out = parse_results(tavily_response, credits=1)
    assert out.results_seen == 20 and len(out.candidates) == 13 and out.skipped_not_product == 5
    assert out.candidates[0].retailer == "Blackberrys" and out.candidates[0].relevance == pytest.approx(0.902, abs=0.001)
    scores = [c.relevance for c in out.candidates]
    assert scores == sorted(scores, reverse=True)  # Tavily's order is kept: relevance, best first
    assert {c.domain for c in out.candidates} <= set(ALL_DOMAINS)
    assert all(looks_like_product_page(c.url) for c in out.candidates)


def test_real_chinos_and_tee_searches(tavily_chinos, tavily_tee):
    chinos, tee = parse_results(tavily_chinos, credits=1), parse_results(tavily_tee, credits=1)
    assert (len(chinos.candidates), chinos.skipped_not_product) == (9, 10)  # many collection pages and a blog
    assert (len(tee.candidates), tee.skipped_not_product) == (14, 3)
    assert any(c.retailer == "Levi's" for c in chinos.candidates)


def test_the_same_page_with_and_without_www_is_one_candidate(tavily_tee):
    urls = [c.url for c in parse_results(tavily_tee, credits=1).candidates]
    ids = [product_id_for(u) for u in urls]
    assert len(ids) == len(set(ids))


def test_product_ids_are_stable_across_tracking_parameters():
    a = product_id_for("https://www.thesouledstore.com/product/solids-blue-polo-t-shirt?gte=1")
    b = product_id_for("https://thesouledstore.com/product/solids-blue-polo-t-shirt/?ref=newsletter")
    assert a == b and a.startswith("t-") and a != product_id_for("https://www.snitch.com/products/x")


def test_a_response_with_no_results_or_odd_fields_does_not_crash():
    assert parse_results({}, credits=1).candidates == []
    odd = {"results": [{"title": "x", "url": "https://www.snitch.com/products/a", "score": "high"}]}
    only = parse_results(odd, credits=1).candidates
    assert len(only) == 1 and only[0].relevance is None and only[0].snippet == ""


# ---- the request we send ------------------------------------------------------------------------------------------
def cfg(**kw) -> Settings:
    return Settings(tavily_api_key="tvly-test", _env_file=None, **kw)


async def _search(handler, config=None, domains=("snitch.com", "bewakoof.com")):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await TavilySearch(config or cfg(), client).search("blue polo t-shirt for men", list(domains))


async def test_the_request_restricts_to_the_given_domains_and_uses_the_key_in_a_header(tavily_response):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["body"], seen["url"] = request.headers["authorization"], json.loads(request.content), str(request.url)
        return httpx.Response(200, json=tavily_response)

    out = await _search(handler)
    body = seen["body"]
    assert seen["auth"] == "Bearer tvly-test" and "tvly-test" not in seen["url"]  # never in the address
    assert body["include_domains"] == ["snitch.com", "bewakoof.com"]
    assert body["query"] == "blue polo t-shirt for men" and body["search_depth"] == "basic" and body["max_results"] == 20
    # nothing we do not use: the page text and images were measured to be unreliable and made the response 400 KB
    assert "include_raw_content" not in body and "include_images" not in body and "country" not in body
    assert len(out.candidates) == 13 and out.credits == 1


async def test_options_come_from_the_settings():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"results": [], "usage": {"credits": 2}})

    out = await _search(handler, cfg(tavily_search_depth="advanced", tavily_max_results=10, tavily_country="india"))
    assert seen["body"]["search_depth"] == "advanced" and seen["body"]["max_results"] == 10 and seen["body"]["country"] == "india"
    assert out.credits == 2  # what Tavily says it charged


async def test_credits_fall_back_to_the_known_price_when_usage_is_missing():
    basic = await _search(lambda r: httpx.Response(200, json={"results": []}))
    advanced = await _search(lambda r: httpx.Response(200, json={"results": []}), cfg(tavily_search_depth="advanced"))
    assert (basic.credits, advanced.credits) == (1, 2)


async def test_a_missing_key_or_no_stores_refuses_without_calling_out():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail("must not call"))) as client:
        with pytest.raises(UpstreamError, match="TAVILY_API_KEY"):
            await TavilySearch(Settings(tavily_api_key="", _env_file=None), client).search("polo", ["snitch.com"])
        with pytest.raises(UpstreamError, match="no stores"):
            await TavilySearch(cfg(), client).search("polo", [])


async def test_a_rejected_key_fails_at_once_and_an_outage_is_retried():
    seen = []

    def bad_key(request):
        seen.append(1)
        return httpx.Response(401, json={"detail": "Unauthorized"})

    with pytest.raises(UpstreamError) as exc:
        await _search(bad_key)
    assert len(seen) == 1 and exc.value.retryable is False and "tvly" not in str(exc.value)

    flaky = iter([httpx.Response(503), httpx.Response(200, json={"results": []})])
    assert (await _search(lambda r: next(flaky))).candidates == []
