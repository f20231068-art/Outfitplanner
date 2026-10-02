from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from api.agent.graph import OUTFITS_WANTED, build_graph, clamp_to_budget
from api.agent.products import mock_search
from api.agent.schemas import (
    ItemSpec,
    OutfitPlan,
    OutfitSpec,
    PrefsExtraction,
    StyleList,
    StyleOption,
)


class FakeLLM:
    """Scripted stand-in for the chat model: answers each structured-output schema."""

    def __init__(self, plan_calls: list | None = None):
        self.plan_calls = plan_calls if plan_calls is not None else []

    def with_structured_output(self, schema, **_kwargs):
        return _Runner(self, schema)


class _Runner:
    def __init__(self, llm: FakeLLM, schema):
        self.llm, self.schema = llm, schema

    def invoke(self, messages):
        text = " ".join(str(m.content) for m in messages).lower()
        if self.schema is PrefsExtraction:
            return PrefsExtraction(
                budget_inr=4000 if "4000" in text else None,
                occasion="college" if "college" in text else None,
            )
        if self.schema is StyleList:
            return StyleList(
                styles=[
                    StyleOption(id=f"s{i}", name=f"Style {i}", description="d", image_prompt="p")
                    for i in range(5)
                ]
            )
        if self.schema is OutfitPlan:
            self.llm.plan_calls.append(messages[-1].content)
            return OutfitPlan(outfits=[_spec(i) for i in range(OUTFITS_WANTED)])
        raise AssertionError(f"unexpected schema {self.schema}")


def _item(category, name, cap):
    return ItemSpec(category=category, item=name, color="beige", max_price_inr=cap)


def _spec(i, top_cap=2500, bottom_cap=2500):
    return OutfitSpec(
        top=_item("top", f"shirt{i}", top_cap),
        bottom=_item("bottom", f"pants{i}", bottom_cap),
        rationale=f"outfit {i}",
    )


def _run_to_the_end(graph, config, answers):
    result = graph.invoke({"messages": [("user", "under 4000")]}, config)
    for answer in answers:
        assert result.get("__interrupt__"), "expected the graph to pause"
        result = graph.invoke(Command(resume=answer), config)
    return result


def test_full_flow_pauses_for_missing_gender_then_style_choice():
    graph = build_graph(FakeLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    first = graph.invoke({"messages": [("user", "under 4000")]}, config)
    assert first["__interrupt__"][0].value["type"] == "ask"  # occasion missing
    assert "occasion" in first["__interrupt__"][0].value["question"]

    second = graph.invoke(Command(resume="college"), config)
    assert second["__interrupt__"][0].value["type"] == "choose_style"
    assert len(second["__interrupt__"][0].value["styles"]) == 5

    final = graph.invoke(Command(resume="s2"), config)
    assert len(final["outfits"]) == OUTFITS_WANTED
    assert all(o["total_inr"] <= 4000 for o in final["outfits"])
    assert final["chosen_style"]["id"] == "s2"


def test_gender_is_never_asked_for_menswear_only_app():
    graph = build_graph(FakeLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "t0"}}
    first = graph.invoke({"messages": [("user", "college wear under 4000")]}, config)
    assert first["__interrupt__"][0].value["type"] == "choose_style"  # went straight to styles


def test_state_survives_between_calls_via_checkpointer():
    graph = build_graph(FakeLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "t2"}}
    graph.invoke({"messages": [("user", "under 4000")]}, config)
    saved = graph.get_state(config)
    assert saved.values["prefs"] == {"budget_inr": 4000}
    assert saved.next == ("ask_user",)


def test_empty_search_retries_then_gives_up():
    llm = FakeLLM()
    graph = build_graph(llm, lambda spec: [], MemorySaver())  # search never finds anything
    config = {"configurable": {"thread_id": "t3"}}
    final = _run_to_the_end(graph, config, ["college", "s0"])
    assert final["outfits"] == []
    assert len(llm.plan_calls) == 3  # first plan + 2 retries, then it stops
    assert "couldn't find all 4" in final["messages"][-1].content


def test_retry_only_asks_for_missing_outfits():
    llm = FakeLLM()
    calls = {"n": 0}

    def flaky_search(spec):
        calls["n"] += 1
        return [] if calls["n"] <= 4 else mock_search(spec)  # first outfits' searches fail

    graph = build_graph(llm, flaky_search, MemorySaver())
    final = _run_to_the_end(graph, {"configurable": {"thread_id": "t4"}}, ["college", "s0"])
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
    assert PrefsExtraction(budget_inr="\u20b93500").budget_inr == 3500
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
    res = graph.invoke({"messages": [("user", "college under 4000")]}, cfg)
    assert calls["n"] >= 2
    assert res["__interrupt__"][0].value["type"] == "choose_style"


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
        graph.invoke({"messages": [("user", "x")]}, {"configurable": {"thread_id": "broken"}})
