"""The conversation never ends: after styles or outfits are shown the shopper can type anything, and the agent
continues from the right node using the saved state."""

import json

import pytest
from langchain_core.exceptions import OutputParserException
from langgraph.checkpoint.memory import MemorySaver

from api.agent.graph import (
    OUTFITS_WANTED,
    apply_edit,
    build_graph,
    latest_round,
    new_budget,
    variety_problems,
)
from api.agent.products import mock_search
from api.agent.schemas import (
    OutfitPlan,
    OutfitSpec,
    RefinementEdit,
    SlotEdit,
    TurnIntent,
)
from tests.test_agent import FakeLLM, _item, _spec, say


def _with_outfits(llm=None, search=mock_search, thread="c"):
    """A conversation that already has its first set of four outfits on screen."""
    llm = llm or FakeLLM()
    graph = build_graph(llm, search, MemorySaver())
    config = {"configurable": {"thread_id": thread}}
    say(graph, config, "college wear under 4000")
    state = say(graph, config, "Style 1", choice="s1")
    assert state["phase"] == "outfits_shown"
    return llm, graph, config, state


# ---- "cheaper": a vague word becomes a number, in code --------------------------------------------------------
def test_cheaper_plans_again_with_a_lower_budget_and_never_repeats_a_product():
    llm = FakeLLM(intents=[TurnIntent(intent="refine")], edits=[RefinementEdit(cheaper=True)])
    _, graph, config, first = _with_outfits(llm)
    first_urls = {p["url"] for o in first["shown"] for p in (o["top"], o["bottom"])}

    second = say(graph, config, "can you show cheaper ones")

    assert len(second["outfits"]) == OUTFITS_WANTED
    assert second["prefs"]["budget_inr"] < 4000  # persisted: the shopper's budget has changed
    assert all(o["total_inr"] <= second["prefs"]["budget_inr"] for o in second["outfits"])
    assert not first_urls & {p["url"] for o in second["outfits"] for p in (o["top"], o["bottom"])}
    assert {o["round"] for o in second["shown"]} == {1, 2} and len(second["shown"]) == 2 * OUTFITS_WANTED
    context = json.loads(llm.plan_calls[-1])
    assert context["refinement"]["budget_inr"] == second["prefs"]["budget_inr"]
    assert len(context["already_shown"]) == OUTFITS_WANTED  # the planner is told what not to repeat


def test_new_budget_rules():
    cheaper, pricier = RefinementEdit(cheaper=True), RefinementEdit(pricier=True)
    assert new_budget(4000, cheaper, [3600, 3200]) == 2850  # 20% under the dearest shown, in steps of 50
    assert new_budget(4000, cheaper, [5000]) == 3200  # never based on more than the budget
    assert new_budget(4000, pricier, []) == 5000
    assert new_budget(4000, RefinementEdit(budget_inr=1500, cheaper=True), [3600]) == 1500  # a figure wins
    assert new_budget(4000, RefinementEdit(note="more formal"), [3600]) == 4000  # unrelated changes keep it


# ---- the compound example: "more like the 3rd, cheaper, bottom in purple, under 1500" -------------------------
def test_compound_edit_anchors_on_the_third_outfit_and_applies_every_change():
    edit = RefinementEdit(anchor=3, relation="more_like", bottom=SlotEdit(color="purple"), budget_inr=1500)
    llm = FakeLLM(intents=[TurnIntent(intent="refine")], edits=[edit])
    _, graph, config, first = _with_outfits(llm)

    state = say(graph, config, "Show more like the 3rd one, but cheaper, and make the bottom purple, under 1500")

    # the planner was handed the exact spec that found outfit 3, not a guess from its title
    anchor = json.loads(llm.plan_calls[-1])["refinement"]["anchor"]
    assert anchor["number"] == 3 and anchor["spec"] == first["shown"][2]["spec"]
    # every new outfit: bottom purple (a shopper colour: searched AND checked), top colour stays hidden
    assert len(state["outfits"]) == OUTFITS_WANTED
    for o in state["outfits"]:
        assert o["spec"]["bottom"]["color"] == "purple" and o["spec"]["bottom"]["color_source"] == "user"
        assert o["spec"]["top"]["color_source"] == "planner"
        assert o["total_inr"] <= 1500
    assert state["prefs"]["budget_inr"] == 1500
    assert state["refinements"][-1]["anchor"] == 3  # recorded: the parsed edit is the "last intent"


def test_keep_copies_the_anchor_piece_and_colour_edits_are_per_round():
    anchor = _spec(7)
    edit = RefinementEdit(top=SlotEdit(keep=True), bottom=SlotEdit(item="chinos", color="purple"))
    planned = [_spec(1), _spec(2)]
    out = apply_edit(planned, edit, anchor)
    assert all(o.top.item == "shirt7" and o.top.color_source == "anchor" for o in out)
    assert all(o.bottom.item == "chinos" and o.bottom.color == "purple" and o.bottom.color_source == "user" for o in out)
    assert planned[0].bottom.color_source == "planner"  # the plan itself is not mutated


def test_the_models_own_colours_are_always_hidden_hints_even_if_it_claims_otherwise():
    class Sneaky(FakeLLM):
        def with_structured_output(self, schema, **kw):
            runner = super().with_structured_output(schema, **kw)

            class R:
                def invoke(self, messages):
                    result = runner.invoke(messages)
                    if isinstance(result, OutfitPlan):
                        for s in result.outfits:
                            s.top.color_source = s.bottom.color_source = "user"
                    return result

            return R()

    _, _, _, state = _with_outfits(Sneaky())
    assert all(o["spec"]["top"]["color_source"] == "planner" for o in state["outfits"])


# ---- reference problems and impossible requests never reach the search ----------------------------------------
def test_an_outfit_number_that_does_not_exist_asks_which_one_without_searching():
    llm = FakeLLM(intents=[TurnIntent(intent="refine")], edits=[RefinementEdit(anchor=9)])
    _, graph, config, first = _with_outfits(llm)
    planned_before = len(llm.plan_calls)

    state = say(graph, config, "more like the 9th one")

    assert "Which one did you mean" in state["messages"][-1].content
    assert len(llm.plan_calls) == planned_before and state["shown"] == first["shown"]
    assert state["phase"] == "outfits_shown"


def test_a_budget_too_low_for_two_garments_is_explained_not_searched():
    llm = FakeLLM(intents=[TurnIntent(intent="refine")], edits=[RefinementEdit(budget_inr=200)])
    _, graph, config, first = _with_outfits(llm)
    state = say(graph, config, "under 200")
    assert "lowest I can search" in state["messages"][-1].content
    assert state["prefs"]["budget_inr"] == 4000 and len(state["shown"]) == len(first["shown"])


# ---- every other kind of message keeps the conversation going ------------------------------------------------
def test_a_question_is_answered_without_searching_and_keeps_the_outfits():
    searches = {"n": 0}

    def counting(spec):
        searches["n"] += 1
        return mock_search(spec)

    llm = FakeLLM(intents=[TurnIntent(intent="question")])
    _, graph, config, first = _with_outfits(llm, counting)
    before = searches["n"]
    state = say(graph, config, "why is the first one a good pick?")
    assert state["messages"][-1].content == "answer" and llm.calls["AnswerOut"] == 1
    assert searches["n"] == before and state["shown"] == first["shown"] and state["phase"] == "outfits_shown"
    facts = json.loads(llm.seen["AnswerOut"])  # the answer is grounded in what was actually shown
    assert [o["number"] for o in facts["outfits"]] == [1, 2, 3, 4] and facts["question"].startswith("why is the first")
    assert facts["outfits"][0]["top"] == first["shown"][0]["top"]["title"]


def test_unclear_messages_get_guidance_instead_of_a_dead_end():
    llm = FakeLLM(intents=[TurnIntent(intent="unclear")])
    _, graph, config, _ = _with_outfits(llm)
    state = say(graph, config, "thanks!")
    assert "more like the 2nd one" in state["messages"][-1].content
    assert state["phase"] == "outfits_shown"


def test_changing_only_the_budget_replans_with_the_same_style():
    llm = FakeLLM(intents=[TurnIntent(intent="change_prefs")])
    _, graph, config, _first = _with_outfits(llm)
    state = say(graph, config, "make my budget 3000")
    assert state["prefs"]["budget_inr"] == 3000 and state["chosen_style"]["id"] == "s1"
    assert state["phase"] == "outfits_shown" and state["round"] == 2
    assert llm.calls["StyleList"] == 1  # styles were NOT proposed again
    assert all(o["total_inr"] <= 3000 for o in state["outfits"])


def test_changing_the_occasion_starts_again_from_styles():
    llm = FakeLLM(intents=[TurnIntent(intent="change_prefs")])
    _, graph, config, first = _with_outfits(llm)
    state = say(graph, config, "actually it is for the office")
    assert state["prefs"]["occasion"] == "office" and state["phase"] == "choosing_style"
    assert llm.calls["StyleList"] == 2 and state["chosen_style"] is None
    assert state["shown"] == first["shown"]  # what was shown stays on record


def test_asking_for_other_styles_proposes_new_ones_and_says_what_was_seen():
    llm = FakeLLM(intents=[TurnIntent(intent="more_styles")])
    graph = build_graph(llm, mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "ms"}}
    say(graph, config, "college wear under 4000")
    state = say(graph, config, "show me different styles")
    assert state["phase"] == "choosing_style" and llm.calls["StyleList"] == 2
    assert "already saw" in llm.seen["StyleList"] and "Style 0" in llm.seen["StyleList"]


def test_a_brand_new_request_drops_old_wishes_but_keeps_what_was_shown():
    llm = FakeLLM(intents=[TurnIntent(intent="new_request")])
    _, graph, config, first = _with_outfits(llm)
    graph.update_state(config, {"prefs": {**first["prefs"], "requests": "suits"}})
    state = say(graph, config, "now I need office wear under 2000")
    assert "requests" not in state["prefs"] and state["prefs"]["budget_inr"] == 2000
    assert state["phase"] == "choosing_style" and state["shown"] == first["shown"]


def test_typing_a_different_style_after_outfits_plans_a_new_round():
    llm = FakeLLM(intents=[TurnIntent(intent="choose_style", style="Style 3")])
    _, graph, config, _first = _with_outfits(llm)
    state = say(graph, config, "let us try the style 3 one")
    assert state["chosen_style"]["id"] == "s3" and state["round"] == 2 and len(state["shown"]) == 2 * OUTFITS_WANTED


def test_typing_your_own_style_works_while_styles_are_listed():
    llm = FakeLLM(intents=[TurnIntent(intent="choose_style", style="something like old money")])
    graph = build_graph(llm, mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "own"}}
    say(graph, config, "college wear under 4000")
    state = say(graph, config, "something like old money")
    assert state["chosen_style"] == {"id": "custom", "name": "something like old money", "description": "something like old money"}
    assert len(state["outfits"]) == OUTFITS_WANTED


# ---- cost and robustness --------------------------------------------------------------------------------------
def test_a_clicked_style_card_does_not_ask_the_model_to_interpret_it():
    llm = FakeLLM()
    graph = build_graph(llm, mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "click"}}
    say(graph, config, "college wear under 4000")
    say(graph, config, "Style 2", choice="s2")
    assert "TurnIntent" not in llm.calls


@pytest.mark.parametrize("phase_setup,expected", [("choosing", "choose_style"), ("shown", "refine")])
def test_an_unreadable_router_answer_falls_back_by_phase(phase_setup, expected):
    class BrokenRouter(FakeLLM):
        def with_structured_output(self, schema, **kw):
            runner = super().with_structured_output(schema, **kw)

            class R:
                def invoke(self, messages):
                    if schema is TurnIntent:
                        raise OutputParserException("unreadable")
                    return runner.invoke(messages)

            return R()

    llm = BrokenRouter()
    graph = build_graph(llm, mock_search, MemorySaver())
    config = {"configurable": {"thread_id": f"fb-{phase_setup}"}}
    state = say(graph, config, "college wear under 4000")
    if phase_setup == "shown":
        state = say(graph, config, "Style 0", choice="s0")
    state = say(graph, config, "cheaper please" if phase_setup == "shown" else "my own style")
    assert state["phase"] == "outfits_shown"  # either way the shopper got outfits, not an error
    assert (state["refinements"] if expected == "refine" else [state["chosen_style"]]) != []


# ---- variety: different garments, not one idea repeated -------------------------------------------------------
def test_variety_problems_flag_repeated_tops_and_bottoms():
    same_top = [OutfitSpec(top=_item("top", "polo shirt", 2000), bottom=_item("bottom", f"pants{i}", 2000), rationale="r") for i in range(2)]
    assert "same kind of top" in variety_problems(same_top)[0]
    varied = [_spec(1), _spec(2), _spec(3)]
    assert variety_problems(varied) == [] and variety_problems(varied[:1]) == []


def test_the_planner_is_asked_once_more_when_it_repeats_garments():
    class Repeats(FakeLLM):
        def with_structured_output(self, schema, **kw):
            runner = super().with_structured_output(schema, **kw)

            class R:
                def invoke(self, messages):
                    result = runner.invoke(messages)
                    if isinstance(result, OutfitPlan) and len(self_outer.plan_calls) == 1:
                        for s in result.outfits:
                            s.top.item = "polo"  # all four tops the same
                    return result

            self_outer = self
            return R()

    llm = Repeats()
    _, _, _, state = _with_outfits(llm)
    assert len(llm.plan_calls) == 2 and "same kind of top" in json.loads(llm.plan_calls[1])["planner_notes"][0]
    assert len(state["outfits"]) == OUTFITS_WANTED


def test_latest_round_is_what_outfit_numbers_refer_to():
    shown = [{"round": 1, "id": "a"}, {"round": 1, "id": "b"}, {"round": 2, "id": "c"}]
    assert [o["id"] for o in latest_round(shown)] == ["c"] and latest_round([]) == []
