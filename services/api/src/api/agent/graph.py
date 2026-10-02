"""Stylist agent: gather prefs -> propose styles -> user picks -> plan outfits -> search -> validate.

Nodes read the shared state and return only the fields they change. Edges (some conditional)
decide what runs next. `interrupt()` pauses the graph; the checkpointer saves the state so a
session can resume later.
"""

import json

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from api.agent.find import find_products_for_specs
from api.agent.products import ProductSearch
from api.agent.prompts import load_prompt
from api.agent.schemas import (
    FindProductsInput,
    Outfit,
    OutfitPlan,
    OutfitSpec,
    PrefsExtraction,
    StyleList,
)
from api.agent.state import StylistState
from api.config import settings

REQUIRED_PREFS = ["budget_inr", "occasion"]  # menswear only: gender is never asked
OUTFITS_WANTED = 4
MAX_RETRIES = 2
MODEL_ATTEMPTS = 3  # re-ask the model when its structured output fails validation

_QUESTIONS = {
    "budget_inr": "What's your total budget for the outfit, in rupees?",
    "occasion": "What's the occasion (college, office, party, everyday casual...)?",
}


def clamp_to_budget(spec: OutfitSpec, budget: int) -> OutfitSpec:
    """Safety net: the LLM is told to respect the budget, but we enforce it in code."""
    total = spec.top.max_price_inr + spec.bottom.max_price_inr
    if total <= budget:
        return spec
    scale = budget / total
    top = spec.top.model_copy(update={"max_price_inr": int(spec.top.max_price_inr * scale)})
    bottom = spec.bottom.model_copy(update={"max_price_inr": int(spec.bottom.max_price_inr * scale)})
    return spec.model_copy(update={"top": top, "bottom": bottom})


def _outfit_is_verified(outfit: dict) -> bool:
    """Second line of defence: every item must carry a passing verification report."""
    o = Outfit.model_validate(outfit)
    return all(p.verification is not None and p.verification.is_match for p in (o.top, o.bottom))


def build_graph(llm, search: ProductSearch, checkpointer=None):
    def structured(schema, system: str, human: str | None = None, history=None):
        messages = [SystemMessage(system), *(history or [])]
        if human:
            messages.append(HumanMessage(human))
        runner = llm.with_structured_output(schema, method=settings.structured_output_method)
        for attempt in range(MODEL_ATTEMPTS):
            try:
                return runner.invoke(messages)
            except (ValidationError, OutputParserException):
                if attempt == MODEL_ATTEMPTS - 1:
                    raise  # the model kept returning unusable output

    # ---- nodes -------------------------------------------------------------------------
    def gather_prefs(state: StylistState):
        extracted = structured(
            PrefsExtraction, load_prompt("extract_prefs"), history=state["messages"]
        )
        prefs = dict(state.get("prefs") or {})
        prefs.update({k: v for k, v in extracted.model_dump().items() if v is not None})
        return {"prefs": prefs, "missing": [f for f in REQUIRED_PREFS if f not in prefs]}

    def ask_user(state: StylistState):
        question = _QUESTIONS[state["missing"][0]]
        answer = interrupt({"type": "ask", "question": question, "missing": state["missing"]})
        return {"messages": [AIMessage(question), HumanMessage(answer)]}

    def propose_styles(state: StylistState):
        result = structured(
            StyleList, load_prompt("propose_styles"), f"Shopper preferences: {state['prefs']}"
        )
        return {"styles": [s.model_dump() for s in result.styles]}

    def wait_for_choice(state: StylistState):
        choice = interrupt({"type": "choose_style", "styles": state["styles"]})
        key = str(choice).strip().lower()
        for style in state["styles"]:
            if key in (style["id"].lower(), style["name"].lower()):
                return {"chosen_style": style}
        # free text, e.g. "something like old-money": let the planner interpret it
        return {"chosen_style": {"id": "custom", "name": str(choice), "description": str(choice)}}

    def plan_outfits(state: StylistState):
        existing = state.get("outfits") or []
        need = OUTFITS_WANTED - len(existing)
        budget = state["prefs"]["budget_inr"]
        context = {
            "preferences": state["prefs"],
            "chosen_style": state["chosen_style"],
            "outfits_needed": need,
            "already_chosen": [o["rationale"] for o in existing],
            "planner_notes": state.get("notes") or [],
        }
        plan = structured(OutfitPlan, load_prompt("plan_outfits", 2), json.dumps(context))
        specs = [clamp_to_budget(s, budget) for s in plan.outfits[:need]]
        return {"outfit_specs": [s.model_dump() for s in specs], "notes": []}

    def find_products(state: StylistState):
        result = find_products_for_specs(
            FindProductsInput(
                specs=[OutfitSpec.model_validate(s) for s in state["outfit_specs"]],
                budget_inr=state["prefs"]["budget_inr"],
                exclude_urls=[
                    p["url"] for o in state.get("outfits") or [] for p in (o["top"], o["bottom"])
                ],
            ),
            search,
        )
        outfits = list(state.get("outfits") or []) + [o.model_dump() for o in result.outfits]
        # tell the planner exactly why items were not usable, so it can propose alternatives
        notes = [f"Spec {u.spec_index + 1} ({u.item}): {u.reason}" for u in result.unfilled]
        return {
            "outfits": outfits,
            "notes": notes,
            "rejected": [r.model_dump() for r in result.rejected],
            "search_errors": result.search_errors,
        }

    def rank_and_validate(state: StylistState):
        budget = state["prefs"]["budget_inr"]
        valid = [
            o for o in state["outfits"] if o["total_inr"] <= budget and _outfit_is_verified(o)
        ]
        valid.sort(key=lambda o: o.get("confidence") != "high")  # confirmed outfits first (stable)
        update: dict = {"outfits": valid}
        if len(valid) < OUTFITS_WANTED:
            update["retries"] = state.get("retries", 0) + 1
        return update

    def respond(state: StylistState):
        outfits = state["outfits"]
        lines = [f"Here are {len(outfits)} outfits for your {state['chosen_style']['name']} look:"]
        for i, o in enumerate(outfits, 1):
            lines.append(
                f"{i}. {o['top']['title']} ({o['top']['retailer']}, ₹{o['top']['price_inr']}) + "
                f"{o['bottom']['title']} ({o['bottom']['retailer']}, ₹{o['bottom']['price_inr']})"
                f" = ₹{o['total_inr']}" + ("  (colour not confirmed by the store)" if o.get("confidence") == "low" else "")
            )
        errors = state.get("search_errors") or []
        if not outfits and errors:  # nothing to show because the search itself was unavailable
            return {
                "messages": [
                    AIMessage(
                        "I couldn't search the stores just now: " + " ".join(errors)
                        + " Please try again in a few minutes."
                    )
                ]
            }
        if len(outfits) < OUTFITS_WANTED:
            if errors:
                lines.append("Some searches were unavailable, so I could only find a few. " + " ".join(errors))
            else:
                lines.append("I couldn't find all 4 within your budget; try a higher budget or another style.")
        return {"messages": [AIMessage("\n".join(lines))]}

    # ---- edges -------------------------------------------------------------------------
    def after_gather(state: StylistState):
        return "ask_user" if state["missing"] else "propose_styles"

    def after_validate(state: StylistState):
        # if the search itself was unavailable, replanning cannot help and would only spend more calls
        if state.get("search_errors"):
            return "respond"
        if len(state["outfits"]) >= OUTFITS_WANTED or state.get("retries", 0) > MAX_RETRIES:
            return "respond"
        return "plan_outfits"

    g = StateGraph(StylistState)
    for name, fn in [
        ("gather_prefs", gather_prefs),
        ("ask_user", ask_user),
        ("propose_styles", propose_styles),
        ("wait_for_choice", wait_for_choice),
        ("plan_outfits", plan_outfits),
        ("find_products", find_products),
        ("rank_and_validate", rank_and_validate),
        ("respond", respond),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "gather_prefs")
    g.add_conditional_edges("gather_prefs", after_gather, ["ask_user", "propose_styles"])
    g.add_edge("ask_user", "gather_prefs")  # re-check after the user answers
    g.add_edge("propose_styles", "wait_for_choice")
    g.add_edge("wait_for_choice", "plan_outfits")
    g.add_edge("plan_outfits", "find_products")
    g.add_edge("find_products", "rank_and_validate")
    g.add_conditional_edges("rank_and_validate", after_validate, ["plan_outfits", "respond"])
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)
