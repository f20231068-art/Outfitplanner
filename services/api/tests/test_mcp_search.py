"""The agent's connection to the MCP tool server, tested against a small in-process fake server."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from langgraph.checkpoint.memory import MemorySaver

from api.agent.graph import build_graph
from api.agent.mcp_search import McpProductSearch, product_from_tool_result
from api.agent.products import SearchUnavailable
from api.agent.schemas import ItemSpec
from tests.test_agent import FakeLLM

SPEC = ItemSpec(category="bottom", item="chinos", color="beige", fit="slim", max_price_inr=2000)

TOOL_ITEM = {
    "product_id": "p1", "title": "Men's Beige Slim Chinos", "retailer": "Snitch", "price_inr": 1200,
    "mrp_inr": 2000, "url": "https://www.snitch.com/products/beige-slim-chinos", "url_kind": "retailer",
    "image_url": "https://img/x.jpg", "description": "Slim fit beige chinos for men", "relevance": 0.87,
    "rating": 4.2, "reviews": 31, "delivery": "Free delivery", "extraction": "store_page",
    "in_stock": True, "attributes": {"color": "Beige", "fabric": "Cotton"},
}


def fake_server(results=None, error: str | None = None, seen: list | None = None) -> FastMCP:
    server = FastMCP("fake-tools")

    @server.tool
    def search_products(item: str, max_price_inr: int, color: str | None = None, fit: str | None = None,
                        fabric: str | None = None, store_groups: list[str] | None = None, limit: int = 20) -> dict:
        if seen is not None:
            seen.append({"item": item, "color": color, "max_price_inr": max_price_inr, "fit": fit,
                         "fabric": fabric, "store_groups": store_groups, "limit": limit})
        if error:
            raise ToolError(error)
        return {"results": results if results is not None else [TOOL_ITEM], "warnings": []}

    return server


def searcher(server, **kw) -> McpProductSearch:
    return McpProductSearch("user_42", client_factory=lambda: Client(server), **kw)


# ---- mapping --------------------------------------------------------------------------------
def test_a_tool_result_becomes_a_product_with_everything_the_tool_gave():
    p = product_from_tool_result(TOOL_ITEM)
    assert (p.product_id, p.retailer, p.price_inr, p.mrp_inr) == ("p1", "Snitch", 1200, 2000)
    assert p.url_kind == "retailer" and p.rating == 4.2 and p.delivery == "Free delivery"
    assert p.description == "Slim fit beige chinos for men" and p.relevance == 0.87
    assert p.extraction == "store_page" and p.verification is None  # verification is the verifier's job
    assert p.in_stock is True and p.attributes == {"color": "Beige", "fabric": "Cotton"}  # what the store's page stated


def test_search_sends_the_spec_to_the_tool_and_returns_products():
    seen: list = []
    products = searcher(fake_server(seen=seen))(SPEC)
    assert [p.title for p in products] == ["Men's Beige Slim Chinos"]
    assert seen == [{"item": "chinos", "color": "beige", "max_price_inr": 2000, "fit": "slim", "fabric": None,
                     "store_groups": None, "limit": 20}]


def test_the_chosen_store_groups_go_to_the_tool_so_one_search_covers_them_all():
    seen: list = []
    spec = SPEC.model_copy(update={"store_groups": ["streetwear", "denim"]})
    searcher(fake_server(seen=seen))(spec)
    assert seen[0]["store_groups"] == ["streetwear", "denim"]


def test_a_product_with_no_image_is_still_a_product():
    item = {**TOOL_ITEM, "image_url": ""}
    assert product_from_tool_result(item).image_url == ""


def test_optional_fields_are_left_out_when_the_spec_has_none():
    seen: list = []
    searcher(fake_server(seen=seen))(ItemSpec(category="top", item="t-shirt", color="white", max_price_inr=900))
    assert seen[0]["fit"] is None and seen[0]["fabric"] is None


def test_no_results_is_an_empty_list_not_an_error():
    assert searcher(fake_server(results=[]))(SPEC) == []


# ---- failures become a shopper-safe SearchUnavailable -------------------------------------------
def test_a_limit_or_refusal_from_the_server_carries_its_own_message():
    with pytest.raises(SearchUnavailable, match="Too many requests"):
        searcher(fake_server(error="Too many requests. Try again in 20 seconds."))(SPEC)


def test_an_unreachable_server_never_leaks_technical_detail():
    def broken():
        raise ConnectionError("connect to 10.1.2.3:8001 failed: secret internal detail")

    with pytest.raises(SearchUnavailable) as exc:
        McpProductSearch("u", client_factory=broken)(SPEC)
    assert "10.1.2.3" not in str(exc.value) and "secret" not in str(exc.value)
    assert "not reachable" in str(exc.value)


def test_many_searches_can_run_in_parallel_threads_as_find_products_does():
    search = searcher(fake_server())
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(search, [SPEC] * 8))
    assert all(len(r) == 1 for r in results)


# ---- the graph when the search is unavailable ---------------------------------------------------
def _run(search, llm=None, thread="t"):
    llm = llm or FakeLLM()
    graph = build_graph(llm, search, MemorySaver())
    cfg = {"configurable": {"thread_id": thread}}
    graph.invoke({"messages": [("user", "college under 4000")]}, cfg)
    return llm, graph.invoke({"messages": [("user", "Style 0")], "choice": "s0"}, cfg)


def test_when_search_is_down_the_shopper_gets_a_clear_message_and_no_endless_replanning():
    def down(spec):
        raise SearchUnavailable("You have used today's search allowance. It resets at 00:00 UTC.")

    llm, final = _run(down)
    assert final["outfits"] == []
    reply = final["messages"][-1].content
    assert "couldn't search the stores just now" in reply and "allowance" in reply
    assert len(llm.plan_calls) == 1  # no replanning: more attempts would only spend more calls


def test_a_partly_failing_search_still_returns_the_outfits_it_could_build():
    from api.agent.products import mock_search

    calls = {"n": 0}

    def flaky(spec):
        calls["n"] += 1
        if calls["n"] % 4 == 0:
            raise SearchUnavailable("Too many requests. Try again in 5 seconds.")
        return mock_search(spec)

    _, final = _run(flaky)
    reply = final["messages"][-1].content
    assert 0 < len(final["outfits"]) < 4
    assert "unavailable" in reply
