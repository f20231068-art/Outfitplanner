import json
import re

from langgraph.checkpoint.memory import MemorySaver

from api.agent.graph import OUTFITS_WANTED, build_graph, clamp_to_budget
from api.agent.products import mock_search
from api.agent.schemas import (
    AnswerOut,
    ItemSpec,
    OutfitPlan,
    OutfitSpec,
    PrefsExtraction,
    RefinementEdit,
    StyleList,
    StyleOption,
    TurnIntent,
)


def _budget_in(text: str) -> int | None:
    m = re.search(r"\b(\d{3,5})\b", text)
    return int(m.group(1)) if m else None


class FakeLLM:
    """Scripted stand-in for the chat model: answers each structured-output schema.

    `intents` / `edits` are queues of scripted answers for the router and the refinement reader.
    `calls` counts how often each kind of question was asked; `seen` keeps the last prompt of each kind.
    """

    def __init__(self, plan_calls: list | None = None, intents: list | None = None, edits: list | None = None):
        self.plan_calls = plan_calls if plan_calls is not None else []
        self.intents, self.edits = list(intents or []), list(edits or [])
        self.calls: dict[str, int] = {}
        self.seen: dict[str, str] = {}

    def with_structured_output(self, schema, **_kwargs):
        return _Runner(self, schema)


class _Runner:
    def __init__(self, llm: FakeLLM, schema):
        self.llm, self.schema = llm, schema

    def invoke(self, messages):
        name = self.schema.__name__
        self.llm.calls[name] = self.llm.calls.get(name, 0) + 1
        self.llm.seen[name] = str(messages[-1].content)
        humans = [str(m.content).lower() for m in messages if getattr(m, "type", "") == "human"]
        text, last = " ".join(humans), (humans[-1] if humans else "")
        if self.schema is PrefsExtraction:
            return PrefsExtraction(
                budget_inr=_budget_in(last) or _budget_in(text),
                occasion=("office" if "office" in last else "college") if ("office" in last or "college" in text) else None,
            )
        if self.schema is StyleList:
            return StyleList(
                styles=[
                    StyleOption(id=f"s{i}", name=f"Style {i}", description="d", image_prompt="p")
                    for i in range(5)
                ]
            )
        if self.schema is TurnIntent:
            if self.llm.intents:
                return self.llm.intents.pop(0)
            context = json.loads(messages[-1].content)
            return TurnIntent(intent="choose_style" if context["phase"] == "choosing_style" else "refine", style=context["message"])
        if self.schema is RefinementEdit:
            return self.llm.edits.pop(0) if self.llm.edits else RefinementEdit(cheaper=True)
        if self.schema is AnswerOut:
            return AnswerOut(text="answer")
        if self.schema is OutfitPlan:
            self.llm.plan_calls.append(messages[-1].content)
            shown = len(json.loads(messages[-1].content)["already_shown"])  # later rounds plan different garments
            return OutfitPlan(outfits=[_spec(shown + i) for i in range(OUTFITS_WANTED)])
        raise AssertionError(f"unexpected schema {self.schema}")


def _item(category, name, cap):
    return ItemSpec(category=category, item=name, color="beige", max_price_inr=cap)


def _spec(i, top_cap=2500, bottom_cap=2500):
    return OutfitSpec(
        top=_item("top", f"shirt{i}", top_cap),
        bottom=_item("bottom", f"pants{i}", bottom_cap),
        rationale=f"outfit {i}",
    )


def say(graph, config, text, choice=None):
    """One shopper message (typed, or a clicked style card when `choice` is given). Returns the saved state."""
    return graph.invoke({"messages": [("user", text)], "choice": choice}, config)


def _run_to_the_end(graph, config, answers=("college", "s0")):
    say(graph, config, "under 4000")
    say(graph, config, answers[0])
    return say(graph, config, f"Style {answers[1][1:]}", choice=answers[1])


def test_full_flow_asks_then_offers_styles_then_plans_outfits():
    graph = build_graph(FakeLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    first = say(graph, config, "under 4000")
    assert first["phase"] == "gathering"  # occasion missing
    assert "occasion" in first["pending_question"]

    second = say(graph, config, "college")
    assert second["phase"] == "choosing_style"
    assert len(second["styles"]) == 5

    final = say(graph, config, "Style 2", choice="s2")
    assert len(final["outfits"]) == OUTFITS_WANTED
    assert all(o["total_inr"] <= 4000 for o in final["outfits"])
    assert final["chosen_style"]["id"] == "s2"
    assert final["phase"] == "outfits_shown"
    assert len(final["shown"]) == OUTFITS_WANTED and {o["round"] for o in final["shown"]} == {1}


def test_gender_is_never_asked_for_menswear_only_app():
    graph = build_graph(FakeLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "t0"}}
    first = say(graph, config, "college wear under 4000")
    assert first["phase"] == "choosing_style"  # went straight to styles


def test_state_survives_between_calls_via_checkpointer():
    graph = build_graph(FakeLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}
    say(graph, config, "under 4000")
    saved = graph.get_state(config)
    assert saved.values["prefs"] == {"budget_inr": 4000}
    assert saved.values["phase"] == "gathering"
    assert saved.next == ()  # the turn finished; nothing is paused, the next message simply continues


def test_empty_search_retries_then_gives_up():
    llm = FakeLLM()
    graph = build_graph(llm, lambda spec: [], MemorySaver())  # search never finds anything
    config = {"configurable": {"thread_id": "t3"}}
    final = _run_to_the_end(graph, config)
    assert final["outfits"] == []
    assert len(llm.plan_calls) == 3  # first plan + 2 retries, then it stops
    assert "couldn't find all 4" in final["messages"][-1].content
    assert final["phase"] == "choosing_style"  # nothing to refine, so the style cards stay on offer


def test_retry_only_asks_for_missing_outfits():
    llm = FakeLLM()
    calls = {"n": 0}

    def flaky_search(spec):
        calls["n"] += 1
        return [] if calls["n"] <= 4 else mock_search(spec)  # first outfits' searches fail

    graph = build_graph(llm, flaky_search, MemorySaver())
    final = _run_to_the_end(graph, {"configurable": {"thread_id": "t4"}})
    assert len(final["outfits"]) == OUTFITS_WANTED
    assert len(llm.plan_calls) == 2


def test_clamp_to_budget_scales_prices_down():
    spec = clamp_to_budget(_spec(0, top_cap=3000, bottom_cap=3000), budget=4000)
    assert spec.top.max_price_inr + spec.bottom.max_price_inr <= 4000


def test_llm_factory_picks_endpoint_style_from_model_name():
    from api.agent.llm import get_llm
    from api.config import Settings

    base = {"opencode_api_key": "k", "_env_file": None}
    gpt = get_llm(Settings(stylist_model="opencode/gpt-5.5", **base))
    qwen = get_llm(Settings(stylist_model="opencode/qwen3-coder", **base))
    assert gpt.use_responses_api is True
    assert not qwen.use_responses_api
    assert str(qwen.openai_api_base).startswith("https://opencode.ai/zen/v1")


def test_llm_factory_openrouter_model_id_keeps_its_slashes_and_colon():
    from api.agent.llm import get_llm
    from api.config import Settings

    llm = get_llm(
        Settings(
            stylist_model="openrouter/apodex/apodex-1.1-mini:free",
            openrouter_api_key="k",
            _env_file=None,
        )
    )
    assert llm.model_name == "apodex/apodex-1.1-mini:free"
    assert str(llm.openai_api_base) == "https://openrouter.ai/api/v1"


def test_llm_factory_rejects_missing_key_and_unknown_provider():
    import pytest

    from api.agent.llm import get_llm
    from api.config import Settings

    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        get_llm(Settings(stylist_model="openrouter/x/y", _env_file=None))
    with pytest.raises(ValueError, match="Unknown provider"):
        get_llm(Settings(stylist_model="openai/gpt-5", _env_file=None))


def test_prefs_schema_tolerates_text_nulls_and_amount_formats():
    for blank in ("None", "null", "", "unknown", "N/A"):
        parsed = PrefsExtraction(budget_inr=blank, occasion=blank)
        assert parsed.budget_inr is None and parsed.occasion is None
    assert PrefsExtraction(budget_inr="4,000").budget_inr == 4000
    assert PrefsExtraction(budget_inr="Rs 4k").budget_inr == 4000
    assert PrefsExtraction(budget_inr="₹3500").budget_inr == 3500
    assert PrefsExtraction(budget_inr=4000).budget_inr == 4000


def test_a_bad_model_answer_is_retried_then_succeeds():
    from langchain_core.exceptions import OutputParserException

    calls = {"n": 0}

    class Flaky(FakeLLM):
        def with_structured_output(self, schema, **_kwargs):
            good = super().with_structured_output(schema)

            class Runner:
                def invoke(self, messages):
                    calls["n"] += 1
                    if calls["n"] == 1:  # the first answer is unusable
                        raise OutputParserException("bad output")
                    return good.invoke(messages)

            return Runner()

    graph = build_graph(Flaky(), mock_search, MemorySaver())
    cfg = {"configurable": {"thread_id": "flaky"}}
    res = say(graph, cfg, "college under 4000")
    assert calls["n"] >= 2
    assert res["phase"] == "choosing_style"


def test_a_model_that_never_returns_valid_output_eventually_raises():
    import pytest
    from langchain_core.exceptions import OutputParserException

    class Broken(FakeLLM):
        def with_structured_output(self, schema, **_kwargs):
            class Runner:
                def invoke(self, messages):
                    raise OutputParserException("always bad")

            return Runner()

    graph = build_graph(Broken(), mock_search, MemorySaver())
    with pytest.raises(OutputParserException):
        say(graph, {"configurable": {"thread_id": "broken"}}, "x")
