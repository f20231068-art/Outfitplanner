"""What the shopper asked for in each piece ("a white oversized t-shirt and baggy denim jeans") is read into fields,
imposed on every outfit in code, checked on the products, and kept (or updated) as the conversation goes on."""

import json

import pytest
from langgraph.checkpoint.memory import MemorySaver

from api.agent.demo import ScriptedLLM, parse_wishes
from api.agent.graph import (
    apply_wishes,
    build_graph,
    fold_edit_into_wishes,
    variety_problems,
    wish_of,
)
from api.agent.products import mock_search
from api.agent.prompts import load_prompt
from api.agent.schemas import (
    GarmentWish,
    ItemSpec,
    OutfitSpec,
    PrefsExtraction,
    Product,
    RefinementEdit,
    SlotEdit,
)
from api.agent.verify import verify_product
from tests.test_agent import _spec, say

MESSAGE = "I want a white oversized tshirt and denim baggy jeans, budget 4500, for a college fest"


# ---- reading the message -------------------------------------------------------------------------------------------
def test_wishes_are_parsed_and_the_models_none_placeholders_are_cleaned_up():
    p = PrefsExtraction.model_validate(
        {"top": {"item": "t-shirt", "color": "white", "fit": "oversized", "fabric": "None"}, "bottom": "none", "avoid": "black, red"}
    )
    assert p.top == GarmentWish(item="t-shirt", color="white", fit="oversized") and p.bottom is None
    assert p.avoid == ["black", "red"]
    assert PrefsExtraction.model_validate({"top": {}, "avoid": []}).top is None
    assert PrefsExtraction.model_validate({"avoid": ["None"]}).avoid is None


def test_the_demo_reader_gives_each_colour_to_the_garment_it_is_next_to():
    top, bottom = parse_wishes("a white oversized tshirt and denim baggy jeans")
    assert (top.item, top.color, top.fit, top.fabric) == ("t-shirt", "white", "oversized", None)
    assert (bottom.item, bottom.color, bottom.fit, bottom.fabric) == ("jeans", None, "baggy", "denim")
    top, bottom = parse_wishes("white baggy jeans")
    assert top is None and (bottom.item, bottom.color) == ("jeans", "white")


def test_the_extraction_prompt_teaches_where_a_colour_belongs():
    prompt = load_prompt("extract_prefs", 3)
    assert "white oversized tshirt and denim baggy jeans" in prompt and "fabric, not a colour" in prompt


# ---- imposing it on the outfits ------------------------------------------------------------------------------------
PREFS = {
    "top": {"item": "t-shirt", "color": "white", "fit": "oversized"},
    "bottom": {"item": "jeans", "fit": "baggy", "fabric": "denim"}, "avoid": ["black"],
}


def test_the_shoppers_wishes_override_the_planner_in_every_outfit_and_the_planners_colour_stays_a_hint():
    out = apply_wishes([_spec(0), _spec(1)], PREFS)
    for s in out:
        assert (s.top.item, s.top.fit, s.top.color, s.top.color_source) == ("t-shirt", "oversized", "white", "user")
        assert set(s.top.fixed) == {"item", "fit", "color"}
        assert (s.bottom.item, s.bottom.fit, s.bottom.fabric) == ("jeans", "baggy", "denim")
        assert s.bottom.color_source == "planner" and "color" not in s.bottom.fixed  # the shopper gave the jeans no colour
        assert s.top.avoid_colors == s.bottom.avoid_colors == ["black"]


def test_with_no_wishes_the_planner_is_left_alone():
    s = apply_wishes([_spec(0)], {"budget_inr": 4000})[0]
    assert (s.top.item, s.top.fixed, s.top.avoid_colors) == ("shirt0", [], [])


def test_a_fixed_piece_is_not_asked_to_vary_but_an_open_piece_is():
    same_tops = [OutfitSpec(top=_spec(0).top.model_copy(update={"item": "t-shirt"}), bottom=_spec(i).bottom, rationale="r") for i in range(3)]
    assert variety_problems(same_tops, tops=False) == []
    assert any("top" in p for p in variety_problems(same_tops))


def test_the_pages_colour_is_checked_against_a_colour_to_avoid():
    spec = apply_wishes([_spec(0)], {"avoid": ["black"]})[0].top.model_copy(update={"item": "shirt0"})

    def product(colour):
        return Product(title="Shirt0 for men", retailer="X", price_inr=900, url="https://x/1", image_url="https://i",
                       attributes={"gender": "men", **({"color": colour} if colour else {})})

    black = verify_product(product("Jet Black"), spec)
    assert not black.is_match and "avoid" in black.blocking
    assert verify_product(product("Olive"), spec).is_match
    unknown = verify_product(product(None), spec)  # the page states no colour: not rejected here (the reader may judge it)
    assert unknown.is_match and next(c for c in unknown.checks if c.attribute == "avoid").status == "unknown"


def test_a_change_to_a_piece_the_shopper_fixed_replaces_that_wish_but_other_pieces_stay_one_round_changes():
    edit = RefinementEdit(top=SlotEdit(color="navy"), bottom=SlotEdit(color="black"))
    prefs = fold_edit_into_wishes({"top": {"item": "t-shirt", "color": "white"}}, edit)
    assert prefs["top"] == {"item": "t-shirt", "color": "navy"}  # white -> navy for good
    assert "bottom" not in prefs  # nothing was fixed for the bottom, so black is for this round only
    assert wish_of({}, "top") is None and wish_of({"top": {"item": None}}, "top") is None


# ---- through the whole agent ------------------------------------------------------------------------------------------
@pytest.fixture
def conversation():
    graph = build_graph(ScriptedLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "wishes"}}
    first = say(graph, config, MESSAGE)
    assert first["phase"] == "choosing_style"
    return graph, config


def test_the_wishes_are_saved_as_fields_and_survive_to_the_outfits(conversation):
    graph, config = conversation
    prefs = graph.get_state(config).values["prefs"]
    assert prefs["top"] == {"item": "t-shirt", "color": "white", "fit": "oversized"}
    assert prefs["bottom"] == {"item": "jeans", "fit": "baggy", "fabric": "denim"}

    state = say(graph, config, "Streetwear", choice="streetwear")
    outfits = state["outfits"]
    assert len(outfits) >= 3
    for o in outfits:
        assert o["spec"]["top"]["color_source"] == "user" and o["spec"]["top"]["color"] == "white"
        assert "White" in o["top"]["title"] and "Oversized" in o["top"]["title"]  # every top is the white oversized tee
        assert "Jeans" in o["bottom"]["title"]
        assert o["top"]["verification"]["is_match"] and o["bottom"]["verification"]["is_match"]
    assert len({o["top"]["url"] for o in outfits}) == len(outfits)  # four outfits, four different white tees


def test_the_planner_is_told_what_the_shopper_fixed(conversation):
    seen = {}

    class Recording(ScriptedLLM):
        def with_structured_output(self, schema, **kw):
            runner = super().with_structured_output(schema, **kw)
            if schema.__name__ != "OutfitPlan":
                return runner

            class Spy:
                def invoke(self, messages):
                    seen["context"] = json.loads(messages[-1].content)
                    seen["system"] = messages[0].content
                    return runner.invoke(messages)

            return Spy()

    graph = build_graph(Recording(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "spy"}}
    say(graph, config, MESSAGE)
    say(graph, config, "Streetwear", choice="streetwear")
    assert seen["context"]["preferences"]["top"]["color"] == "white" and seen["context"]["preferences"]["bottom"]["fabric"] == "denim"
    assert "FIXED" in seen["system"]


def test_a_follow_up_colour_change_replaces_the_fixed_colour_for_later_rounds(conversation):
    graph, config = conversation
    say(graph, config, "Streetwear", choice="streetwear")
    state = say(graph, config, "make the top navy")
    assert state["prefs"]["top"]["color"] == "navy"
    again = say(graph, config, "make it cheaper")
    assert all(o["spec"]["top"]["color"] == "navy" for o in again["outfits"])  # it did not quietly go back to white


# ---- settings -----------------------------------------------------------------------------------------------------
def test_model_calls_have_a_time_limit_and_the_reader_is_on_by_default():
    from api.agent.llm import get_llm
    from api.config import Settings

    cfg = Settings(stylist_model="openrouter/openai/gpt-6-luna", openrouter_api_key="k", _env_file=None)
    llm = get_llm(cfg)
    assert llm.request_timeout == 60.0 and llm.max_retries == 1
    assert cfg.ai_judge is True and cfg.judge_search_retries == 1 and cfg.judge_max_candidates == 12
    assert Settings(_env_file=None).stylist_model  # the default is a real setting
    assert ItemSpec(category="top", item="x", max_price_inr=1).fixed == []


def test_bookkeeping_fields_a_planner_fills_in_are_ignored():
    from api.agent.graph import _planner_colours_only

    cheeky = _spec(0).top.model_copy(update={"keywords": "graphic print", "fixed": ["item"], "avoid_colors": ["red"], "color_source": "user"})
    out = _planner_colours_only(OutfitSpec(top=cheeky, bottom=_spec(0).bottom, rationale="r")).top
    assert (out.keywords, out.fixed, out.avoid_colors, out.color_source) == (None, [], [], "planner")


def test_a_fixed_garment_with_no_colour_drops_the_planners_colour_hint_so_the_outfits_share_one_search():
    out = apply_wishes([_spec(0), _spec(1)], {"bottom": {"item": "jeans", "fabric": "denim"}})
    assert all(s.bottom.color is None for s in out)  # was a different hint per outfit
    assert out[0].top.color == _spec(0).top.color  # a piece the shopper left open keeps its hint


def test_the_title_can_confirm_a_fabric_the_pages_material_field_only_names_as_its_fibre():
    spec = ItemSpec(category="bottom", item="shorts", fabric="denim", max_price_inr=3000)
    snitch = Product(title="Core Lab Denim Baggy Shorts", retailer="Snitch", price_inr=1900, url="https://s/1", image_url="https://i",
                     attributes={"fabric": "Cotton", "gender": "men"})
    report = verify_product(snitch, spec)
    assert report.is_match and next(c for c in report.checks if c.attribute == "fabric").status == "match"
    other = snitch.model_copy(update={"title": "Core Lab Baggy Shorts"})  # nothing says denim, and the page says cotton
    assert next(c for c in verify_product(other, spec).checks if c.attribute == "fabric").status == "mismatch"


def test_no_second_plan_when_the_shopper_fixed_both_garments(monkeypatch):
    plans = []

    class Counting(ScriptedLLM):
        def with_structured_output(self, schema, **kw):
            runner = super().with_structured_output(schema, **kw)
            if schema.__name__ == "OutfitPlan":
                plans.append(1)
            return runner

    # every search comes back empty, which normally makes the agent plan again (up to 3 rounds)
    graph = build_graph(Counting(), lambda spec: [], MemorySaver())
    config = {"configurable": {"thread_id": "fixed-both"}}
    say(graph, config, MESSAGE)
    say(graph, config, "Streetwear", choice="streetwear")
    assert len(plans) == 1
    plans.clear()
    other = {"configurable": {"thread_id": "open-pieces"}}
    say(graph, other, "college fest, budget 4500")
    say(graph, other, "Streetwear", choice="streetwear")
    assert len(plans) == 3  # with nothing fixed, a new plan can help, so the agent still tries


def test_a_title_that_says_jeans_confirms_denim():
    spec = ItemSpec(category="bottom", item="jeans", fabric="denim", max_price_inr=3000)
    light_wash = Product(title="Light Blue Distressed Loose Fit Jeans", retailer="Snitch", price_inr=1900, url="https://s/2",
                         image_url="https://i", attributes={"fabric": "Cotton", "gender": "men"})
    assert verify_product(light_wash, spec).is_match
    chinos = Product(title="Beige Chinos", retailer="X", price_inr=1900, url="https://s/3", image_url="https://i", attributes={"gender": "men"})
    assert next(c for c in verify_product(chinos, spec.model_copy(update={"item": "chinos"})).checks if c.attribute == "fabric").status == "unknown"


def test_a_fixed_garment_gets_a_generous_price_cap_but_an_open_piece_keeps_the_planners():
    from api.agent.graph import widen_fixed_caps

    planned = _spec(0, top_cap=1000, bottom_cap=1800)
    wished = apply_wishes([planned], {"top": {"item": "t-shirt"}})[0]
    out = widen_fixed_caps(wished, 4500)
    assert out.top.max_price_inr == 2025  # 45% of the budget, up from the planner's 1000
    assert out.bottom.max_price_inr == 1800  # not fixed by the shopper: the planner's split stands
    assert widen_fixed_caps(wished, 1000).top.max_price_inr == 1000  # never lowered


def test_the_reply_blames_the_exact_match_not_the_budget_when_the_shopper_fixed_pieces():
    graph = build_graph(ScriptedLLM(), lambda spec: [], MemorySaver())  # no store has anything
    config = {"configurable": {"thread_id": "reply"}}
    say(graph, config, MESSAGE)
    reply = say(graph, config, "Streetwear", choice="streetwear")["messages"][-1].content
    assert "matches exactly what you asked for" in reply and "budget" in reply.split("exactly")[1]  # advice, not blame
    open_graph = build_graph(ScriptedLLM(), lambda spec: [], MemorySaver())
    other = {"configurable": {"thread_id": "reply2"}}
    say(open_graph, other, "college fest, budget 4500")
    assert "within your budget" in say(open_graph, other, "Streetwear", choice="streetwear")["messages"][-1].content


def test_pieces_typed_as_the_style_are_read_like_a_first_message():
    graph = build_graph(ScriptedLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "typed-style"}}
    say(graph, config, "college fest, budget 4500")
    assert "top" not in graph.get_state(config).values["prefs"]  # nothing fixed yet
    state = say(graph, config, "a grey oversized T-shirt and dark baggy jeans")
    assert state["prefs"]["top"] == {"item": "t-shirt", "color": "grey", "fit": "oversized"}
    assert state["prefs"]["bottom"]["item"] == "jeans" and state["prefs"]["bottom"]["fit"] == "baggy"
    assert state["prefs"]["budget_inr"] == 4500  # what was already known is kept
    assert len(state["outfits"]) >= 3
    assert all("Grey" in o["top"]["title"] and "Oversized" in o["top"]["title"] for o in state["outfits"])  # not a polo, not an overshirt


def test_stores_name_olive_in_other_words_and_the_rules_know_it():
    from api.agent.verify import colour_search_words

    spec = ItemSpec(category="top", item="t-shirt", color="olive", color_source="user", max_price_inr=2000)

    def tee(colour):
        return Product(title="Oversized T-Shirt", retailer="X", price_inr=900, url="https://x/1", image_url="https://i",
                       attributes={"color": colour, "gender": "men"})

    assert verify_product(tee("Army Green"), spec).is_match and verify_product(tee("Olive Green"), spec).is_match
    assert not verify_product(tee("Sky Blue"), spec).is_match and not verify_product(tee("Trekking Green"), spec).is_match
    assert colour_search_words("olive") == "army green" and colour_search_words("black") is None


# ---- colours the style card names -------------------------------------------------------------------------------------
def test_a_colour_the_chosen_style_names_becomes_a_verified_colour_but_the_planners_own_does_not():
    from api.agent.graph import apply_style_colours

    spec = OutfitSpec(top=_spec(0).top.model_copy(update={"color": "dark olive"}),
                      bottom=_spec(0).bottom.model_copy(update={"color": "charcoal"}), rationale="r")
    out = apply_style_colours([spec], "Olive polo & beige chinos: relaxed smart casual")[0]
    assert (out.top.color, out.top.color_source) == ("olive", "style")  # 'dark' was the planner's; the card said olive
    assert (out.bottom.color, out.bottom.color_source) == ("charcoal", "planner")  # not on the card: a hint only
    shopper = OutfitSpec(top=_spec(0).top.model_copy(update={"color": "white", "color_source": "user"}), bottom=_spec(0).bottom, rationale="r")
    assert apply_style_colours([shopper], "White shirt")[0].top.color_source == "user"  # the shopper's own stays theirs


def test_a_style_colour_is_checked_on_the_product_like_a_colour_the_shopper_asked_for():
    spec = _spec(0).top.model_copy(update={"item": "shirt0", "color": "olive", "color_source": "style"})

    def tee(colour):
        return Product(title="Shirt0 for men", retailer="X", price_inr=900, url="https://x/1", image_url="https://i",
                       attributes={"color": colour, "gender": "men"})

    assert verify_product(tee("Army Green"), spec).is_match and not verify_product(tee("Sky Blue"), spec).is_match


def test_the_chosen_style_travels_with_every_piece_to_the_search_and_its_colours_are_verified():
    seen = []

    def search(spec):
        seen.append((spec.category, spec.color, spec.color_source, spec.style))
        return mock_search(spec)

    graph = build_graph(ScriptedLLM(), search, MemorySaver())
    config = {"configurable": {"thread_id": "style-colours"}}
    say(graph, config, "college fest, budget 4500")
    say(graph, config, "Streetwear", choice="streetwear")
    assert seen and all(s[3] and s[3].startswith("Streetwear") for s in seen)  # the look is passed on every search
