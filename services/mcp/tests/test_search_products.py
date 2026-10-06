import httpx
import pytest
from fastmcp import Client

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.net import UpstreamError, get_json
from mcp_server.providers.page_facts import PageFacts
from mcp_server.providers.tavily import TavilySearch, parse_results
from mcp_server.sellers import GROUPS, domains_for
from mcp_server.server import build_server
from mcp_server.tools.search_products import build_query, run_search
from tests.fakes import FakePages, FakeTavily
from tests.keys import PUBLIC_PEM

CFG = Settings(tavily_api_key="tvly-test", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None)


def run(provider, pages=None, *, cfg=CFG, cache=None, refs=None, facts=None, failed=None, **kw):
    args = {"item": "polo t-shirt", "color": "blue", "max_price_inr": 5000, **kw}
    return run_search(
        provider, cache or TTLCache(60), refs or TTLCache(60), cfg, page_reader=pages or FakePages(),
        facts_cache=facts or TTLCache(60), failed_cache=failed or TTLCache(60), **args,
    )


def good(price=999, **kw) -> PageFacts:
    return PageFacts(name="A real product", price_inr=price, image_url="https://img.example/p.jpg", in_stock=True, **kw)


# ---- query building ----------------------------------------------------------------------------
def test_query_always_says_men_and_drops_repeated_words():
    assert build_query("polo t-shirt", "blue") == "blue polo t-shirt for men"
    assert build_query("oversized t-shirt", "black", "oversized", "cotton") == "black oversized cotton t-shirt for men"
    assert build_query("mens chinos") == "mens chinos"


def test_colour_is_optional_and_left_out_of_the_query():
    assert build_query("polo", None, "slim") == "slim polo for men"
    assert build_query("polo", "navy blue", "slim") == "navy blue slim polo for men"


# ---- discovery: ONE search covers a whole group of stores -------------------------------------------------
async def test_one_search_covers_every_store_in_the_chosen_groups(tavily_response):
    provider = FakeTavily(tavily_response)
    out = await run(provider, store_groups=["streetwear", "denim"])
    assert provider.calls == 1  # not one per store
    assert provider.last_domains == domains_for(["streetwear", "denim"]) and len(provider.last_domains) == 37
    assert out.store_groups == ["streetwear", "denim"] and out.stores_searched == 37 and out.credits_spent == 1
    assert provider.last_query == "blue polo t-shirt for men" == out.query_used


async def test_no_groups_means_every_store_and_group_order_never_changes_the_search(tavily_response):
    out = await run(FakeTavily(tavily_response))
    assert out.store_groups == list(GROUPS) and out.stores_searched == 100
    cache, p = TTLCache(60), FakeTavily(tavily_response)
    await run(p, cache=cache, store_groups=["denim", "streetwear"])
    again = await run(p, cache=cache, store_groups=["streetwear", "denim"])
    assert p.calls == 1 and again.from_cache  # the same search in a different order is the same search


async def test_second_identical_search_is_served_from_cache_and_costs_nothing(tavily_response):
    provider, cache = FakeTavily(tavily_response), TTLCache(60)
    first = await run(provider, cache=cache)
    second = await run(provider, cache=cache)
    assert provider.calls == 1  # the credit was spent once
    assert (first.from_cache, second.from_cache) == (False, True) and (first.credits_spent, second.credits_spent) == (1, 0)
    assert first.results == second.results


# ---- reading: price, image and stock come from the store's own page ---------------------------------------
async def test_only_the_best_candidates_are_read_and_their_facts_become_the_product(tavily_response):
    candidates = parse_results(tavily_response, credits=1).candidates
    pages = FakePages({c.url: good(1000 + i) for i, c in enumerate(candidates)})
    out = await run(FakeTavily(tavily_response), pages, cfg=Settings(page_reads_per_search=4, page_read_batch=4, enough_products=99, _env_file=None))
    assert pages.calls == [c.url for c in candidates[:4]] and out.pages_read == 4  # the 4 most relevant, no more
    assert [r.price_inr for r in out.results] == [1000, 1001, 1002, 1003]
    first = out.results[0]
    assert first.title == "A real product" and first.retailer == candidates[0].retailer and first.url == candidates[0].url
    assert first.image_url == "https://img.example/p.jpg" and first.in_stock is True and first.relevance == candidates[0].relevance


async def test_a_page_that_cannot_be_read_states_no_price_or_is_sold_out_is_not_returned(tavily_response):
    candidates = parse_results(tavily_response, credits=1).candidates
    pages = FakePages({
        candidates[0].url: None,  # blocked
        candidates[1].url: PageFacts(name="x", price_inr=None, in_stock=True),  # no price
        candidates[2].url: PageFacts(name="x", price_inr=900, in_stock=False),  # sold out
        candidates[3].url: good(1200),
    })
    out = await run(FakeTavily(tavily_response), pages, cfg=Settings(page_reads_per_search=4, page_read_batch=4, enough_products=99, _env_file=None))
    assert [r.price_inr for r in out.results] == [1200]
    codes = {w.code: w.count for w in out.warnings}
    assert codes["PAGE_UNREADABLE"] == 1 and codes["NO_PRICE"] == 1 and codes["OUT_OF_STOCK"] == 1 and codes["NOT_A_PRODUCT_PAGE"] == 5


async def test_what_the_page_says_about_colour_and_fabric_comes_through(tavily_response):
    facts = good(980, color="Purple", material="Cotton")
    out = await run(FakeTavily(tavily_response), FakePages({parse_results(tavily_response, credits=1).candidates[0].url: facts}))
    assert out.results[0].attributes == {"color": "Purple", "fabric": "Cotton"}


async def test_a_page_read_once_is_remembered_and_so_is_a_failure(tavily_response, tavily_tee):
    candidates = parse_results(tavily_response, credits=1).candidates
    pages = FakePages({candidates[0].url: None})
    facts, failed = TTLCache(60), TTLCache(60)
    cfg = Settings(page_reads_per_search=3, page_read_batch=3, enough_products=99, _env_file=None)
    await run(FakeTavily(tavily_response), pages, cfg=cfg, facts=facts, failed=failed)
    first_calls = len(pages.calls)
    assert first_calls == 3
    await run(FakeTavily(tavily_response), pages, cfg=cfg, cache=TTLCache(60), facts=facts, failed=failed)  # a fresh search
    assert len(pages.calls) == first_calls  # the same pages: nothing read again, and the blocked one is not retried


async def test_price_cap_filters_and_limit_truncates(tavily_response):
    pages = FakePages({c.url: good(500 + i * 400) for i, c in enumerate(parse_results(tavily_response, credits=1).candidates)})
    cheap = await run(FakeTavily(tavily_response), pages, max_price_inr=1000)
    assert cheap.results and all(r.price_inr <= 1000 for r in cheap.results)
    assert "PRICE_OVER_CAP" in {w.code for w in cheap.warnings}
    two = await run(FakeTavily(tavily_response), pages, limit=2)
    assert len(two.results) == 2


async def test_every_product_is_remembered_so_the_buy_link_needs_no_new_search(tavily_response):
    refs = TTLCache(60)
    out = await run(FakeTavily(tavily_response), refs=refs)
    assert out.results and all(refs.get(r.product_id) is not None for r in out.results)


async def test_pages_are_read_in_parallel_up_to_the_limit(tavily_response):
    import asyncio

    active = {"now": 0, "max": 0}

    async def slow(url):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.02)
        active["now"] -= 1
        return good()

    await run(FakeTavily(tavily_response), slow, cfg=Settings(page_reads_per_search=8, page_read_batch=3, enough_products=99, _env_file=None))
    assert 1 < active["max"] <= 3


async def test_reading_stops_as_soon_as_there_are_enough_products(tavily_response):
    pages = FakePages()  # every page is fine
    out = await run(FakeTavily(tavily_response), pages, cfg=Settings(enough_products=4, page_read_batch=5, _env_file=None))  # batches of 5
    assert out.pages_read == 5 and len(pages.calls) == 5 and len(out.results) == 5  # one batch was plenty
    assert Settings(_env_file=None).enough_products == 8  # by default it reads on, so the agent has fits to choose from


async def test_when_the_top_candidates_are_sold_out_it_keeps_reading_down_the_list(tavily_response):
    candidates = parse_results(tavily_response, credits=1).candidates
    sold_out = {c.url: PageFacts(name="x", price_inr=900, in_stock=False) for c in candidates[:5]}
    pages = FakePages(sold_out)
    out = await run(FakeTavily(tavily_response), pages, cfg=Settings(enough_products=4, _env_file=None))
    assert out.pages_read == 10 and len(out.results) == 5  # the first batch was all sold out, so a second was read
    assert next(w for w in out.warnings if w.code == "OUT_OF_STOCK").count == 5


async def test_it_never_reads_more_pages_than_the_limit_even_if_nothing_is_usable(tavily_response):
    pages = FakePages({c.url: None for c in parse_results(tavily_response, credits=1).candidates})
    out = await run(FakeTavily(tavily_response), pages, cfg=Settings(page_reads_per_search=7, _env_file=None))
    assert out.results == [] and out.pages_read == 7 and len(pages.calls) == 7


async def test_a_pages_junk_product_name_is_replaced_by_the_tidied_search_title(tavily_response):
    candidates = parse_results(tavily_response, credits=1).candidates
    pages = FakePages({candidates[0].url: PageFacts(name="Default Title", price_inr=900, in_stock=True)})
    out = await run(FakeTavily(tavily_response), pages)
    assert out.results[0].title == candidates[0].title and out.results[0].title != "Default Title"


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
    provider = TavilySearch(Settings(tavily_api_key="", _env_file=None), client=None)
    with pytest.raises(UpstreamError, match="TAVILY_API_KEY"):
        await provider.search("blue polo t-shirt for men", ["snitch.com"])


# ---- through a real MCP client ------------------------------------------------------------
async def test_tool_is_discoverable_and_callable_through_mcp(tavily_response):
    provider = FakeTavily(tavily_response)
    server = build_server(CFG, provider=provider, page_reader=FakePages())
    async with Client(server) as client:
        tools = {t.name: t for t in await client.list_tools()}
        assert {"ping", "search_products"} <= set(tools)

        schema = tools["search_products"].input_schema
        assert set(schema["required"]) == {"item", "max_price_inr"}  # optional ones (colour, groups) are not required
        assert "description" in schema["properties"]["color"] and "description" in schema["properties"]["store_groups"]
        assert "keywords" in schema["properties"] and "keywords" not in schema["required"]
        assert "streetwear" in str(schema["properties"]["store_groups"]) and "activewear" in str(schema["properties"]["store_groups"])

        result = await client.call_tool(
            "search_products",
            {"item": "polo t-shirt", "color": "blue", "max_price_inr": 5000, "limit": 3, "store_groups": ["streetwear"]},
        )
        data = result.structured_content
        assert data["query_used"] == "blue polo t-shirt for men" and len(data["results"]) == 3
        assert data["results"][0]["price_inr"] > 0 and data["results"][0]["image_url"] and data["schema_version"] == "1"
        assert data["store_groups"] == ["streetwear"] and data["stores_searched"] == 30 and data["credits_spent"] == 1
        assert data["pages_read"] == 10 and data["results"][0]["extraction"] == "store_page"  # reads on until 8 are usable
        assert provider.last_domains == domains_for(["streetwear"])


async def test_an_unknown_store_group_is_rejected_by_the_schema_before_any_search(tavily_response):
    provider = FakeTavily(tavily_response)
    server = build_server(CFG, provider=provider, page_reader=FakePages())
    async with Client(server) as client:
        with pytest.raises(Exception):  # noqa: B017 - any MCP error is fine, it must not return data
            await client.call_tool("search_products", {"item": "polo", "max_price_inr": 5000, "store_groups": ["amazon"]})
    assert provider.calls == 0


async def test_invalid_arguments_are_rejected_by_the_schema_before_our_code_runs(tavily_response):
    server = build_server(CFG, provider=FakeTavily(tavily_response), page_reader=FakePages())
    async with Client(server) as client:
        with pytest.raises(Exception):  # noqa: B017 - any MCP error is fine, it must not return data
            await client.call_tool("search_products", {"item": "polo", "color": "blue", "max_price_inr": -5})


async def test_provider_outage_becomes_a_clean_tool_error():
    class Down:
        async def search(self, query, domains, context=None):
            raise UpstreamError("search provider unavailable after 3 tries (HTTP 503)", retryable=True)

    server = build_server(CFG, provider=Down(), page_reader=FakePages())
    async with Client(server) as client:
        with pytest.raises(Exception, match="You can retry"):
            await client.call_tool("search_products", {"item": "polo", "color": "blue", "max_price_inr": 5000})


# ---- retry keywords and the page's own description -------------------------------------------------------------
def test_keywords_widen_the_query_and_only_safe_characters_get_through():
    from mcp_server.tools.search_products import MAX_KEYWORDS_CHARS, clean_keywords

    assert build_query("t-shirt", "white", "oversized", None, "boxy drop-shoulder") == "white oversized t-shirt boxy drop-shoulder for men"
    assert clean_keywords("boxy; fit & (drop) <b>shoulder</b>") == "boxy fit drop b shoulder b"
    assert clean_keywords(None) == "" and len(clean_keywords("word " * 60)) <= MAX_KEYWORDS_CHARS


async def test_a_search_with_keywords_is_a_different_search(tavily_response):
    provider, cache = FakeTavily(tavily_response), TTLCache(60)
    first = await run(provider, cache=cache)
    second = await run(provider, cache=cache, keywords="relaxed boxy")
    assert provider.calls == 2 and second.credits_spent == 1  # new words, new search, new credit
    assert second.query_used == "blue polo t-shirt relaxed boxy for men" and first.query_used == "blue polo t-shirt for men"


async def test_the_pages_own_description_is_passed_on_for_the_reader(tavily_response):
    async def pages(url):
        return good(details="100% cotton oversized tee in off white")

    out = await run(FakeTavily(tavily_response), pages)
    assert out.results and all(r.details == "100% cotton oversized tee in off white" for r in out.results)


async def test_an_empty_answer_from_the_search_provider_is_not_remembered(tavily_response):
    cache = TTLCache(60)
    empty = FakeTavily({**tavily_response, "results": []})
    first = await run(empty, cache=cache)
    assert first.results == [] and first.credits_spent == 1
    again = await run(empty, cache=cache)
    assert empty.calls == 2 and not again.from_cache  # asked again, not served a remembered blank
    good_provider = FakeTavily(tavily_response)
    assert (await run(good_provider, cache=cache)).results  # and a later real answer is found
