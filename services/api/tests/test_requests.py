"""The shopper's own wishes ("preferably suits") must reach the style and outfit prompts, and the style prompt
must not hand the model a stock list of trend names to copy."""

import json

from langgraph.checkpoint.memory import MemorySaver

from api.agent.graph import build_graph
from api.agent.products import mock_search
from api.agent.prompts import load_prompt
from api.agent.schemas import OutfitPlan, PrefsExtraction, StyleList, StyleOption
from tests.test_agent import _spec


class RecordingLLM:
    """Reads 'suits' out of the conversation like a model would, and records what each prompt contained."""

    def __init__(self):
        self.seen: dict[str, str] = {}

    def with_structured_output(self, schema, **_kwargs):
        return _Runner(self, schema)


class _Runner:
    def __init__(self, llm, schema):
        self.llm, self.schema = llm, schema

    def invoke(self, messages):
        text = " ".join(str(m.content) for m in messages).lower()
        if self.schema is PrefsExtraction:
            return PrefsExtraction(
                budget_inr=4000 if "4000" in text else None,
                occasion="college reunion" if "reunion" in text else None,
                requests="suits" if "suits" in text else None,
            )
        if self.schema is StyleList:
            self.llm.seen["styles"] = messages[-1].content
            return StyleList(
                styles=[StyleOption(id=f"s{i}", name=f"S{i}", description="d", image_prompt="p") for i in range(5)]
            )
        if self.schema is OutfitPlan:
            self.llm.seen["plan"] = messages[-1].content
            return OutfitPlan(outfits=[_spec(i) for i in range(4)])
        raise AssertionError(self.schema)


def test_requests_are_extracted_kept_and_passed_to_both_prompts():
    llm = RecordingLLM()
    graph = build_graph(llm, mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "r1"}}

    first = graph.invoke({"messages": [("user", "a college reunion, preferably suits, under 4000")]}, config)
    assert first["phase"] == "choosing_style"
    assert graph.get_state(config).values["prefs"]["requests"] == "suits"
    assert "suits" in llm.seen["styles"] and "college reunion" in llm.seen["styles"]

    graph.invoke({"messages": [("user", "S1")], "choice": "s1"}, config)
    assert json.loads(llm.seen["plan"])["preferences"]["requests"] == "suits"


def test_no_requests_means_the_field_is_absent_not_a_placeholder():
    graph = build_graph(RecordingLLM(), mock_search, MemorySaver())
    config = {"configurable": {"thread_id": "r2"}}
    graph.invoke({"messages": [("user", "a college reunion, under 4000")]}, config)
    assert "requests" not in graph.get_state(config).values["prefs"]


def test_blank_requests_are_treated_as_not_stated():
    assert PrefsExtraction(requests="None").requests is None
    assert PrefsExtraction(requests="  ").requests is None
    assert PrefsExtraction(requests="suits, navy").requests == "suits, navy"


def test_style_prompt_does_not_hand_the_model_stock_trend_names():
    prompt = load_prompt("propose_styles", 2).lower()
    for stock in ("korean casual", "streetwear", "minimalist"):
        assert stock not in prompt, f"the prompt lists {stock!r}; small models copy listed examples"
    assert "requests come first" in prompt


def test_other_prompts_know_about_requests():
    assert "requests" in load_prompt("extract_prefs", 2)
    assert "requests" in load_prompt("plan_outfits", 4)
