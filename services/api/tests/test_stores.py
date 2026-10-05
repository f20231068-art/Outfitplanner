"""Which groups of stores each search covers: the planner chooses, code guarantees every garment has a store."""

import json

import pytest
from langgraph.checkpoint.memory import MemorySaver

from api.agent.graph import OUTFITS_WANTED, assign_groups, build_graph
from api.agent.products import mock_search
from api.agent.schemas import ItemSpec, OutfitPlan, OutfitSpec
from api.agent.stores import GROUPS, clean_groups, default_groups, groups_for_item, resolve_groups
from tests.test_agent import FakeLLM, say


# ---- the pure rules -----------------------------------------------------------------------------------------------
def test_only_real_group_ids_survive_in_canonical_order():
    assert clean_groups(["denim", "STREETWEAR", "amazon", "denim", " traditional "]) == ["streetwear", "denim", "traditional"]
    assert clean_groups(None) == []
    assert OutfitPlan(outfits=[], store_groups="streetwear, smart_casual").store_groups == ["streetwear", "smart_casual"]
    assert OutfitPlan(outfits=[], store_groups=["None", "myntra"]).store_groups == []


def test_the_planner_may_choose_at_most_three_groups_and_a_default_fills_in_when_it_chose_none():
    assert resolve_groups(list(GROUPS), "x") == ["streetwear", "smart_casual", "denim"]
    assert resolve_groups([], "Smart Casual") == ["smart_casual"]
    assert resolve_groups(["nonsense"], "Streetwear") == ["streetwear"]


@pytest.mark.parametrize("style,expected", [
    ("Streetwear: oversized tees and cargos", ["streetwear"]),
    ("Old money classic", ["smart_casual"]),
    ("Wedding guest in ethnic wear", ["traditional", "smart_casual"]),
    ("Retro Sporty track-inspired", ["streetwear", "activewear"]),
    ("Raw denim everything", ["denim", "streetwear"]),
    ("something completely different", ["streetwear", "smart_casual"]),
])
def test_default_groups_read_the_styles_words(style, expected):
    assert default_groups(style) == expected


def test_a_requested_garment_style_can_steer_the_default():
    assert default_groups("Navy two-piece", "preferably suits") == ["smart_casual"]


@pytest.mark.parametrize("item,planned,expected", [
    ("slim jeans", ["streetwear"], ["streetwear", "denim"]),  # denim stores sell jeans: never leave jeans without them
    ("kurta", ["smart_casual"], ["smart_casual", "traditional"]),
    ("joggers", ["streetwear"], ["streetwear", "activewear"]),
    ("polo t-shirt", ["streetwear"], ["streetwear"]),  # nothing extra needed
    ("Nehru jacket", ["streetwear"], ["streetwear", "traditional"]),
])
def test_a_garment_adds_the_group_that_sells_it(item, planned, expected):
    assert groups_for_item(item, planned) == expected


def test_assign_groups_sets_each_garment_separately():
    spec = OutfitSpec(
        top=ItemSpec(category="top", item="polo", max_price_inr=900),
        bottom=ItemSpec(category="bottom", item="jeans", max_price_inr=1500), rationale="r",
    )
    out = assign_groups(spec, ["streetwear"])
    assert out.top.store_groups == ["streetwear"] and out.bottom.store_groups == ["streetwear", "denim"]
    assert spec.top.store_groups == []  # the original is untouched


# ---- through the agent ---------------------------------------------------------------------------------------------
class Recording(FakeLLM):
    """A planner that chooses store groups and plans a jeans outfit, and a search that records its specs."""

    def __init__(self, groups):
        super().__init__()
        self.groups = groups

    def with_structured_output(self, schema, **kw):
        runner = super().with_structured_output(schema, **kw)
        groups = self.groups

        class R:
            def invoke(self, messages):
                result = runner.invoke(messages)
                if isinstance(result, OutfitPlan):
                    result.store_groups = groups
                    result.outfits[0].bottom.item = "jeans"
                return result

        return R()


def _search_recording(seen):
    def search(spec):
        seen.append(spec)
        return mock_search(spec)

    return search


def test_the_planners_groups_reach_every_search_and_jeans_always_get_the_denim_stores():
    seen: list[ItemSpec] = []
    llm = Recording(["streetwear"])
    graph = build_graph(llm, _search_recording(seen), MemorySaver())
    config = {"configurable": {"thread_id": "g1"}}
    say(graph, config, "college wear under 4000")
    state = say(graph, config, "Style 1", choice="s1")

    assert state["store_groups"] == ["streetwear"] and len(state["outfits"]) == OUTFITS_WANTED
    assert len(seen) == 2 * OUTFITS_WANTED  # one search per garment, never one per store
    assert all(s.store_groups[0] == "streetwear" for s in seen)
    jeans = [s for s in seen if s.item == "jeans"]
    assert jeans and all(s.store_groups == ["streetwear", "denim"] for s in jeans)
    assert all("denim" not in s.store_groups for s in seen if s.item != "jeans")  # others skip the denim specialists


def test_when_the_planner_chooses_nothing_the_style_decides():
    seen: list[ItemSpec] = []
    graph = build_graph(Recording([]), _search_recording(seen), MemorySaver())
    config = {"configurable": {"thread_id": "g2"}}
    say(graph, config, "college wear under 4000")
    state = say(graph, config, "Style 1", choice="s1")
    assert state["store_groups"] == ["streetwear", "smart_casual"]  # "Style 1" says nothing: the default pair


def test_the_prompt_shows_the_planner_every_group_it_may_choose():
    from api.agent.prompts import load_prompt

    text = load_prompt("plan_outfits", 5)
    for group in GROUPS:
        assert group in text
    assert json.dumps("store_groups") in text
