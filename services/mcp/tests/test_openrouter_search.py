"""The model-driven search: what it asks OpenRouter for, and what it lets through. No network: the HTTP side is a fake."""

import json

import httpx
import pytest

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.net import UpstreamError, make_client
from mcp_server.providers.openrouter_search import OpenRouterSearch, parse_answer
from mcp_server.sellers import domains_for
from mcp_server.tools.search_products import run_search
from tests.fakes import FakePages

CFG = Settings(openrouter_api_key="sk-or-test-key", search_provider="openrouter", _env_file=None)
DOMAINS = domains_for(["streetwear"])


def product(url="https://khaaki.in/products/toad-olive-oversized-t-shirt", **kw) -> dict:
    return {"title": "Toad - Olive Oversized T-shirt", "url": url, "store": "Khaaki", "colour_stated": "Olive",
            "fit_stated": "Oversized", "price_inr": 849, **kw}


def answer(*products) -> str:
    return "Here you go:\n```json\n" + json.dumps({"products": list(products)}) + "\n```"


def reply(text: str, cost=0.0121) -> dict:
    return {"choices": [{"message": {"content": text}}], "usage": {"cost": cost}}


def provider(handler, cfg=CFG) -> OpenRouterSearch:
    return OpenRouterSearch(cfg, make_client(cfg, transport=httpx.MockTransport(handler)))


# ---- reading the model's answer ------------------------------------------------------------------------------------
def test_the_answer_becomes_candidates_with_what_the_search_stated():
    out = parse_answer(answer(product(), product("https://www.beyoung.in/dark-olive-plain-oversized-t-shirt-for-men", store="Beyoung")))
    assert [c.retailer for c in out.candidates] == ["Khaaki", "Beyoung"]
    assert out.candidates[0].snippet == "The search says colour: Olive; fit: Oversized."
    assert out.candidates[0].title == "Toad - Olive Oversized T-shirt" and out.skipped_not_product == 0


def test_only_single_product_pages_of_approved_stores_get_through():
    out = parse_answer(answer(
        product(),
        product("https://not-on-our-list.example/products/olive-tee"),  # a store we do not list
        product("https://khaaki.in/collections/olive"),  # a collection page
        product("http://khaaki.in/products/plain-http"),  # not https
        product("https://khaaki.in/products/untitled", title=""),  # no title
        "not a product",
    ))
    assert [c.url for c in out.candidates] == ["https://khaaki.in/products/toad-olive-oversized-t-shirt"]
    assert out.skipped_not_product == 5


def test_the_same_page_twice_is_one_candidate_and_the_list_is_capped():
    out = parse_answer(answer(product(), product("https://www.khaaki.in/products/toad-olive-oversized-t-shirt/")))
    assert len(out.candidates) == 1
    many = [product(f"https://khaaki.in/products/tee-{i}") for i in range(30)]
    assert len(parse_answer(answer(*many), limit=5).candidates) == 5


@pytest.mark.parametrize("text", ["I could not find any.", "{not json", json.dumps({"products": "none"}), ""])
def test_an_answer_that_is_not_the_expected_json_is_an_upstream_error(text):
    with pytest.raises(UpstreamError):
        parse_answer(text)


# ---- the request ----------------------------------------------------------------------------------------------------
async def test_the_request_restricts_the_search_to_the_approved_stores_and_carries_the_look():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json=reply(answer(product())))

    out = await provider(handler).search("olive oversized t-shirt for men", DOMAINS, "Olive polo and beige chinos")
    body, tool = seen["body"], seen["body"]["tools"][0]
    assert seen["auth"] == "Bearer sk-or-test-key" and body["model"] == "openai/gpt-6-luna"
    assert tool["type"] == "openrouter:web_search" and tool["parameters"]["allowed_domains"] == DOMAINS
    assert tool["parameters"]["engine"] == "exa" and tool["parameters"]["max_uses"] == 1
    assert "olive oversized t-shirt for men" in body["messages"][1]["content"]
    assert "Olive polo and beige chinos" in body["messages"][1]["content"]
    assert len(out.candidates) == 1 and out.cost_usd == pytest.approx(0.0121) and out.credits == 1


async def test_no_more_domains_are_sent_than_the_filter_honours():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["domains"] = json.loads(request.content)["tools"][0]["parameters"]["allowed_domains"]
        return httpx.Response(200, json=reply(answer(product())))

    everything = domains_for(["streetwear", "smart_casual", "denim", "traditional", "activewear"])
    assert len(everything) == 100
    await provider(handler).search("black baggy pants", everything)
    assert seen["domains"] == everything[:70]


async def test_a_transient_failure_is_retried_once_and_a_refusal_is_not():
    calls = []

    def flaky(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json=reply(answer(product())))

    assert len((await provider(flaky).search("tee", DOMAINS)).candidates) == 1 and len(calls) == 2
    calls.clear()

    def refused(request):
        calls.append(1)
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(UpstreamError) as exc:
        await provider(refused).search("tee", DOMAINS)
    assert len(calls) == 1 and not exc.value.retryable and "bad key" not in str(exc.value)


async def test_without_a_key_or_stores_it_refuses_before_any_request():
    def boom(request):
        raise AssertionError("no request may be made")

    with pytest.raises(UpstreamError, match="OPENROUTER_API_KEY"):
        await provider(boom, Settings(openrouter_api_key="", _env_file=None)).search("tee", DOMAINS)
    with pytest.raises(UpstreamError, match="no stores"):
        await provider(boom).search("tee", [])


async def test_a_response_with_no_message_is_an_upstream_error():
    with pytest.raises(UpstreamError):
        await provider(lambda r: httpx.Response(200, json={"choices": []})).search("tee", DOMAINS)


# ---- through the whole search tool ------------------------------------------------------------------------------------
async def test_the_look_changes_the_cache_key_and_the_cost_is_reported_once():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["messages"][1]["content"])
        return httpx.Response(200, json=reply(answer(product())))

    p, cache = provider(handler), TTLCache(60)

    async def go(style):
        return await run_search(
            p, cache, TTLCache(60), CFG, item="t-shirt", color="olive", max_price_inr=3000, style=style,
            store_groups=["streetwear"], page_reader=FakePages(), facts_cache=TTLCache(60), failed_cache=TTLCache(60),
        )

    first, again, other = await go("Olive polo"), await go("Olive polo"), await go("Black and white")
    assert len(seen) == 2 and again.from_cache and not other.from_cache  # the same look is served from the cache
    assert first.search_cost_usd == pytest.approx(0.0121) and again.search_cost_usd == 0.0
    assert first.results and first.results[0].retailer == "Khaaki"


async def test_the_default_provider_is_the_model_search_and_tavily_is_still_selectable(monkeypatch):
    from mcp_server.server import build_server
    from tests.keys import PUBLIC_PEM

    monkeypatch.delenv("SEARCH_PROVIDER")  # the test suite pins the other provider; this checks the shipped default
    assert Settings(_env_file=None).search_provider == "openrouter"
    build_server(Settings(mcp_jwt_public_key=PUBLIC_PEM, search_provider="tavily", _env_file=None))  # builds without error


# ---- the stores are searched in small chunks, all at once --------------------------------------------------------------
def test_store_groups_are_packed_into_chunks_the_filter_can_honour():
    from mcp_server.tools.search_products import search_chunks

    assert search_chunks(["streetwear"], CFG) == [["streetwear"]]
    assert search_chunks(["streetwear", "smart_casual"], CFG) == [["streetwear"], ["smart_casual"]]  # 30 + 31 is too many for one
    assert search_chunks(["denim", "activewear"], CFG) == [["denim", "activewear"]]  # 7 + 9 fit together
    every = search_chunks(["streetwear", "smart_casual", "denim", "traditional", "activewear"], CFG)
    assert all(sum(len(domains_for([g])) for g in c) <= 35 for c in every)
    assert [g for c in every for g in c] == ["streetwear", "smart_casual", "denim", "traditional", "activewear"]  # none dropped
    other = Settings(search_provider="tavily", _env_file=None)
    assert search_chunks(["streetwear", "smart_casual"], other) == [["streetwear", "smart_casual"]]  # one search for the other provider


async def test_each_chunk_is_its_own_search_run_together_and_the_answers_are_merged_in_turn():
    asked = []

    def handler(request):
        body = json.loads(request.content)
        domains = body["tools"][0]["parameters"]["allowed_domains"]
        asked.append(domains)
        store = "streetwear" if domains == domains_for(["streetwear"]) else "smart"
        urls = [f"https://{'khaaki.in' if store == 'streetwear' else 'andamen.com'}/products/{store}-tee-{i}" for i in range(3)]
        return httpx.Response(200, json=reply(answer(*[product(u, title=f"{store} tee {i}") for i, u in enumerate(urls)])))

    p, cache = provider(handler), TTLCache(60)
    out = await run_search(
        p, cache, TTLCache(60), CFG, item="t-shirt", color="olive", max_price_inr=3000, store_groups=["streetwear", "smart_casual"],
        page_reader=FakePages(), facts_cache=TTLCache(60), failed_cache=TTLCache(60),
    )
    assert sorted(len(d) for d in asked) == [30, 31] and len(asked) == 2  # two searches, each over one group's stores
    assert out.credits_spent == 2 and out.stores_searched == 61 and out.store_groups == ["streetwear", "smart_casual"]
    hosts = [r.url.split("/")[2] for r in out.results]
    assert set(hosts[:2]) == {"khaaki.in", "andamen.com"}  # taken in turn from each chunk, not one chunk after the other


async def test_one_failing_chunk_does_not_lose_the_others_but_all_failing_is_an_error():
    def half(request):
        domains = json.loads(request.content)["tools"][0]["parameters"]["allowed_domains"]
        return httpx.Response(401) if domains == domains_for(["streetwear"]) else httpx.Response(200, json=reply(answer(product())))

    async def go(handler):
        return await run_search(
            provider(handler), TTLCache(60), TTLCache(60), CFG, item="t-shirt", color=None, max_price_inr=3000,
            store_groups=["streetwear", "smart_casual"], page_reader=FakePages(), facts_cache=TTLCache(60), failed_cache=TTLCache(60),
        )

    assert (await go(half)).results  # smart_casual still answered
    with pytest.raises(UpstreamError):
        await go(lambda r: httpx.Response(401))


def test_html_entities_in_a_title_are_decoded():
    from mcp_server.providers.page_facts import PageFacts
    from mcp_server.providers.tavily import Candidate
    from mcp_server.tools.search_products import product_from

    c = Candidate(url="https://rarerabbit.in/products/x", title="x", snippet="", relevance=None, retailer="Rare Rabbit", domain="rarerabbit.in")
    facts = PageFacts(name="Rare Rabbit Men&#39;s Kelos Olive Shirt", price_inr=1439, in_stock=True)
    assert product_from(c, facts).title == "Rare Rabbit Men's Kelos Olive Shirt"
