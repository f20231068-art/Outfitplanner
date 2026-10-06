"""Stylist agent. The conversation never ends: every message goes through `route_turn`, which looks at where
the conversation is (its phase) and what the shopper said, and sends it to the right node.

    START -> route_turn -+-> gather_prefs -> ask_user | propose_styles | restart_plan
                         +-> propose_styles                      (more or different styles)
                         +-> set_style -> plan_outfits           (a style was picked or described)
                         +-> refine -> plan_outfits              (a change to outfits already shown)
                         +-> answer_question                     (a question about what was shown)
                         +-> clarify                             (anything else)
    plan_outfits -> find_products -> rank_and_validate -> respond (loops back to plan_outfits if outfits are short)

Every path ends the turn at END; the saved state (phase, preferences, styles, outfits shown) is what the next
message continues from. Nodes read the shared state and return only the fields they change.

What is decided by the model and what by code:
  model: reading the message (intent, preferences incl. what is wanted in the top and in the bottom, the requested edit),
         designing outfits, reading the real candidate products and judging them against the request, answering questions.
  code:  which anchor outfit "the 3rd one" means, how a budget changes, applying the shopper's wishes and edits to the
         search specs, the variety check, and every product verification (the reader can only drop real products).
"""

import json

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from api.agent.find import find_products_for_specs
from api.agent.judge import make_judge
from api.agent.products import ProductSearch
from api.agent.prompts import load_prompt
from api.agent.schemas import (
    AnswerOut,
    FindProductsInput,
    GarmentWish,
    ItemSpec,
    Outfit,
    OutfitPlan,
    OutfitSpec,
    PrefsExtraction,
    RefinementEdit,
    SlotEdit,
    StyleList,
    TurnIntent,
)
from api.agent.state import StylistState
from api.agent.stores import groups_for_item, resolve_groups, wide_groups
from api.agent.verify import _COLOR_WORDS, _GARMENT_NOUNS, _tokens
from api.config import settings

REQUIRED_PREFS = ["budget_inr", "occasion"]  # menswear only: gender is never asked
OUTFITS_WANTED = 4
_WISH_KEYS = ("requests", "top", "bottom", "avoid")  # what the shopper asked for; a fresh request drops all of it
MAX_RETRIES = 2
MODEL_ATTEMPTS = 3  # re-ask the model when its structured output fails validation
MIN_BUDGET_INR = 600  # below this a top and a bottom together cannot be found
CHEAPER_FACTOR = 0.8  # "cheaper" with no figure: aim about 20% below the dearest outfit just shown
PRICIER_FACTOR = 1.25

GATHERING, CHOOSING, SHOWN = "gathering", "choosing_style", "outfits_shown"  # the conversation's phase

_QUESTIONS = {
    "budget_inr": "What's your total budget for the outfit, in rupees?",
    "occasion": "What's the occasion (college, office, party, everyday casual...)?",
}
_INTENT_TO_NODE = {
    "provide_info": "gather_prefs", "new_request": "gather_prefs", "change_prefs": "gather_prefs",
    "more_styles": "propose_styles", "choose_style": "set_style", "refine": "refine",
    "question": "answer_question", "unclear": "clarify",
}


# ---- pure helpers (no model, no network): easy to test ---------------------------------------------------
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


def latest_round(shown: list[dict]) -> list[dict]:
    """The outfits of the most recent set the shopper was shown, in the order they saw them (1, 2, 3...)."""
    if not shown:
        return []
    last = max(o.get("round", 1) for o in shown)
    return [o for o in shown if o.get("round", 1) == last]


def summarise(outfits: list[dict]) -> list[dict]:
    """A compact, numbered view of outfits for a prompt. Numbers match what the shopper sees on screen."""
    return [
        {
            "number": i, "top": o["top"]["title"], "bottom": o["bottom"]["title"], "total_inr": o["total_inr"],
            "stores": f"{o['top']['retailer']} / {o['bottom']['retailer']}", "why": o.get("rationale", ""),
        }
        for i, o in enumerate(outfits, 1)
    ]


def _garment_key(item: str) -> str:
    tokens = _tokens(item)
    return next((t for t in tokens if t in _GARMENT_NOUNS), " ".join(tokens))


def variety_problems(specs: list[OutfitSpec], tops: bool = True, bottoms: bool = True) -> list[str]:
    """The planner must show different garments, not one idea repeated. Returns what to tell it to fix.
    `tops` / `bottoms` say which pieces are open: a piece the shopper fixed is the same in every outfit on purpose."""
    if len(specs) < 2:
        return []
    problems = []
    if tops and len({_garment_key(s.top.item) for s in specs}) < len(specs):
        problems.append("Two outfits use the same kind of top. Use a different top garment in every outfit.")
    if bottoms and len({_garment_key(s.bottom.item) for s in specs}) < len(specs):
        problems.append("Two outfits use the same kind of bottom. Use a different bottom garment in every outfit.")
    return problems


def new_budget(current: int, edit: RefinementEdit, latest_totals: list[int]) -> int:
    """The budget after a refinement. A stated figure wins; 'cheaper' / 'pricier' are turned into a number here,
    in code, because a vague word must not be left to the model."""
    if edit.budget_inr:
        return edit.budget_inr
    if edit.cheaper:
        base = min(current, max(latest_totals)) if latest_totals else current
        return int(base * CHEAPER_FACTOR) // 50 * 50
    if edit.pricier:
        return int(current * PRICIER_FACTOR) // 50 * 50
    return current


def _edit_slot(base: ItemSpec, edit: SlotEdit | None, anchor: ItemSpec | None) -> ItemSpec:
    if edit is None:
        return base
    spec = base
    if edit.keep and anchor is not None:  # keep this piece exactly as in the anchor outfit
        spec = base.model_copy(update={
            "item": anchor.item, "fit": anchor.fit, "fabric": anchor.fabric, "color": anchor.color,
            "color_source": "user" if anchor.color_source == "user" else "anchor",
        })
    changes: dict = {k: v for k, v in (("item", edit.item), ("fit", edit.fit), ("fabric", edit.fabric)) if v}
    if edit.color:  # a colour the SHOPPER named: searched, checked, and shown
        changes.update(color=edit.color, color_source="user")
    changes["fixed"] = sorted({*spec.fixed, *changes} - {"color_source"})
    return spec.model_copy(update=changes)


def wish_of(prefs: dict, slot: str) -> GarmentWish | None:
    """What the shopper fixed for the top or the bottom (stored in the preferences), if anything."""
    raw = prefs.get(slot)
    wish = GarmentWish.model_validate(raw) if raw else None
    return None if wish is None or wish.is_empty else wish


def _with_wish(base: ItemSpec, wish: GarmentWish | None, avoid: list[str]) -> ItemSpec:
    changes: dict = {"avoid_colors": list(avoid)}
    fixed = list(base.fixed)
    if wish:
        for attr in ("item", "fit", "fabric"):
            if getattr(wish, attr):
                changes[attr] = getattr(wish, attr)
                fixed.append(attr)
        if wish.color:  # a colour the SHOPPER named: searched, checked, and shown
            changes.update(color=wish.color, color_source="user")
            fixed.append("color")
        if wish.item:
            # The shopper fixed the garment, so whatever they did not state stays OPEN: the planner's colour, fit and fabric
            # ideas (a different one per outfit) would only split one search into four thinner ones. The outfits then share
            # one search and take the best matches in turn.
            for attr in ("color", "fit", "fabric"):
                if attr not in fixed:
                    changes[attr] = None
    changes["fixed"] = sorted(set(fixed))
    changes["loose"] = [a for a in base.loose if a not in fixed and changes.get(a, getattr(base, a))]
    return base.model_copy(update=changes)


def apply_wishes(specs: list[OutfitSpec], prefs: dict) -> list[OutfitSpec]:
    """Impose what the shopper asked for in each piece on every planned outfit. Done in code, after the model has planned,
    so "a white oversized t-shirt" stays exactly that whatever the planner chose."""
    top, bottom, avoid = wish_of(prefs, "top"), wish_of(prefs, "bottom"), list(prefs.get("avoid") or [])
    return [
        s.model_copy(update={"top": _with_wish(s.top, top, avoid), "bottom": _with_wish(s.bottom, bottom, avoid)})
        for s in specs
    ]


def fold_edit_into_wishes(prefs: dict, edit: RefinementEdit) -> dict:
    """A change to a piece the shopper had already fixed ("make the top navy" after "a white t-shirt") replaces that wish, so
    the next round does not quietly go back to white. A piece they had not fixed stays a one-round change."""
    prefs = dict(prefs)
    for slot, change in (("top", edit.top), ("bottom", edit.bottom)):
        wish = wish_of(prefs, slot)
        if wish is None or change is None:
            continue
        merged = wish.model_copy(update={k: v for k, v in (
            ("item", change.item), ("color", change.color), ("fit", change.fit), ("fabric", change.fabric)) if v})
        prefs[slot] = merged.model_dump(exclude_none=True)
    return prefs


def apply_edit(specs: list[OutfitSpec], edit: RefinementEdit, anchor: OutfitSpec | None) -> list[OutfitSpec]:
    """Apply the shopper's requested change to every planned outfit. Done in code, after the model has planned,
    so the change holds even if the model ignored it."""
    return [
        s.model_copy(update={
            "top": _edit_slot(s.top, edit.top, anchor.top if anchor else None),
            "bottom": _edit_slot(s.bottom, edit.bottom, anchor.bottom if anchor else None),
        })
        for s in specs
    ]


def _planner_choices_only(item: ItemSpec) -> ItemSpec:
    # the bookkeeping fields belong to the code: a planner that fills them in (it sees them in its output format) would
    # change what is searched and checked, e.g. extra search words would stop four identical pieces sharing one search
    loose = [a for a in ("fit", "fabric") if getattr(item, a)]  # the planner's fit and fabric are hints, like its colour
    return item.model_copy(
        update={"color_source": "planner", "fixed": [], "avoid_colors": [], "keywords": None, "loose": loose}
    )


def _style_colour(item: ItemSpec, style_words: set[str]) -> ItemSpec:
    """A colour the chosen style card itself names ("Olive polo & beige chinos") is a colour the shopper picked, not the
    planner's guess: it is searched and verified. Checked here in code against the card's own words, never taken on trust
    from the planner. 'dark olive' is reduced to the colour the card names ('olive'): the card said olive, not 'dark'."""
    if item.color_source != "planner" or not item.color:
        return item
    tokens = _tokens(item.color)
    core = [t for t in tokens if t in _COLOR_WORDS] or tokens
    if core and all(t in style_words for t in core):
        return item.model_copy(update={"color": " ".join(core), "color_source": "style"})
    return item


def apply_style_colours(specs: list[OutfitSpec], style_text: str) -> list[OutfitSpec]:
    words = set(_tokens(style_text))
    return [
        s.model_copy(update={"top": _style_colour(s.top, words), "bottom": _style_colour(s.bottom, words)}) for s in specs
    ]


def with_style(spec: OutfitSpec, style_line: str) -> OutfitSpec:
    return spec.model_copy(update={
        "top": spec.top.model_copy(update={"style": style_line or None}),
        "bottom": spec.bottom.model_copy(update={"style": style_line or None}),
    })


def _planner_colours_only(spec: OutfitSpec) -> OutfitSpec:
    """Whatever the model wrote, its own colours are a hidden hint: only the shopper's colours are verified."""
    return spec.model_copy(update={"top": _planner_choices_only(spec.top), "bottom": _planner_choices_only(spec.bottom)})


FIXED_TOP_SHARE, FIXED_BOTTOM_SHARE = 0.45, 0.65  # of the budget: what a piece the shopper fixed may cost at most


def widen_fixed_caps(spec: OutfitSpec, budget: int) -> OutfitSpec:
    """The planner splits the budget to suit ITS idea of the outfit. A garment the shopper fixed is not the planner's idea, so
    its price cap must not be an arbitrary guess that rules out good matches: allow it a generous share of the budget (the
    two pieces still have to fit the budget together, which the search checks when it puts the outfit together)."""
    top, bottom = spec.top, spec.bottom
    if "item" in top.fixed:
        top = top.model_copy(update={"max_price_inr": max(top.max_price_inr, int(budget * FIXED_TOP_SHARE))})
    if "item" in bottom.fixed:
        bottom = bottom.model_copy(update={"max_price_inr": max(bottom.max_price_inr, int(budget * FIXED_BOTTOM_SHARE))})
    return spec.model_copy(update={"top": top, "bottom": bottom})


def _groups_for(item: ItemSpec, planned: list[str]) -> list[str]:
    # a garment the shopper fixed is searched everywhere it can be sold; a piece the planner chose, in the planner's groups
    return wide_groups(item.item, planned) if "item" in item.fixed else groups_for_item(item.item, planned)


def assign_groups(spec: OutfitSpec, planned: list[str]) -> OutfitSpec:
    """Tell the search which store groups to cover for each garment: the planned ones plus what the garment needs (and, for a
    garment the shopper fixed, every group that sells it)."""
    return spec.model_copy(update={
        "top": spec.top.model_copy(update={"store_groups": _groups_for(spec.top, planned)}),
        "bottom": spec.bottom.model_copy(update={"store_groups": _groups_for(spec.bottom, planned)}),
    })


def _fresh() -> dict:
    """Forget the working data of the previous round (what was already SHOWN is kept in `shown`)."""
    return {"outfits": [], "outfit_specs": [], "notes": [], "retries": 0, "search_errors": []}


def _merge_prefs(old: dict, extracted: PrefsExtraction) -> dict:
    """The preferences with what was just read added. Only what the shopper stated replaces anything; wishes that came out
    empty are dropped rather than stored."""
    prefs = dict(old)
    prefs.update({k: v for k, v in extracted.model_dump(exclude_none=True).items() if v not in ({}, [])})
    for key in _WISH_KEYS:
        if not prefs.get(key):
            prefs.pop(key, None)
    return prefs


def _style_line(style: dict) -> str:
    """The chosen style as one line for the reader: 'Korean casual: soft pastels, wide trousers'."""
    name, description = style.get("name", ""), style.get("description", "")
    return name if not description or description == name else f"{name}: {description}"


def _last_user_text(state: StylistState) -> str:
    for m in reversed(state.get("messages") or []):
        if getattr(m, "type", "") == "human":
            return str(m.content).strip()
    return ""


def build_graph(llm, search: ProductSearch, checkpointer=None, judge="auto"):
    """`judge`: "auto" = a model reads the candidate products (when AI_JUDGE is on); None = rule-based checks only; or a
    callable (tests)."""

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

    if judge == "auto":
        judge = make_judge(structured) if settings.ai_judge else None

    # ---- routing: what does the latest message mean? -----------------------------------------------------
    def route_turn(state: StylistState):
        text = _last_user_text(state)
        phase = state.get("phase")
        styles, shown = state.get("styles") or [], state.get("shown") or []
        update: dict = {
            "choice": None, "proceed": False, "edit": None, "anchor": None, "style_text": None, "intent": None,
        }
        choice = state.get("choice")
        if choice and phase in (CHOOSING, SHOWN) and any(choice.lower() in (s["id"].lower(), s["name"].lower()) for s in styles):
            return {**update, "intent": "choose_style", "style_text": choice}  # a card click: no model call needed
        if phase in (None, GATHERING):
            return {**update, "intent": "provide_info"}  # we asked a question (or this is the first message)

        context = {
            "phase": phase, "preferences": state.get("prefs") or {}, "message": text,
            "styles_listed": [s["name"] for s in styles] if phase == CHOOSING else [],
            "outfits_shown": summarise(latest_round(shown)),
        }
        try:
            decided = structured(TurnIntent, load_prompt("route_turn"), json.dumps(context))
        except (ValidationError, OutputParserException):  # the model could not be read: fall back by phase
            decided = TurnIntent(intent="choose_style" if phase == CHOOSING else "refine", style=text)
        intent = decided.intent
        # an intent that cannot apply to this conversation is mapped to the nearest one that can
        if intent == "refine" and not shown:
            intent = "change_prefs"
        if intent == "choose_style" and not styles:
            intent = "change_prefs"
        update["intent"] = intent
        update["style_text"] = decided.style or text
        if intent == "new_request":  # a fresh request: drop the old wishes and results, keep what is restated
            prefs = {k: v for k, v in (state.get("prefs") or {}).items() if k not in _WISH_KEYS}
            update.update(prefs=prefs, styles=[], chosen_style=None, **_fresh())
        return update

    # ---- nodes -------------------------------------------------------------------------------------------
    def gather_prefs(state: StylistState):
        extracted = structured(
            PrefsExtraction, load_prompt("extract_prefs", 3), history=state["messages"]
        )
        old = dict(state.get("prefs") or {})
        prefs = _merge_prefs(old, extracted)
        changed = [k for k, v in prefs.items() if v != old.get(k)]
        return {"prefs": prefs, "missing": [f for f in REQUIRED_PREFS if f not in prefs], "changed": changed}

    def ask_user(state: StylistState):
        question = _QUESTIONS[state["missing"][0]]
        return {"messages": [AIMessage(question)], "phase": GATHERING, "pending_question": question}

    def propose_styles(state: StylistState):
        prefs = state["prefs"]
        human = (
            f"Occasion: {prefs.get('occasion')}\nBudget: INR {prefs.get('budget_inr')} for the whole outfit\n"
            f"The shopper asked for: {prefs.get('requests') or 'nothing specific'}"
        )
        seen = [s["name"] for s in state.get("styles") or []]
        if state.get("intent") == "more_styles" and seen:
            human += f"\nThe shopper already saw these and wants different ones: {', '.join(seen)}"
        result = structured(StyleList, load_prompt("propose_styles", 2), human)
        return {
            "styles": [s.model_dump() for s in result.styles], "chosen_style": None, "phase": CHOOSING,
            "messages": [AIMessage("Here are five style directions. Pick one, or describe your own.")],
        }

    def set_style(state: StylistState):
        styles = state.get("styles") or []
        text = (state.get("style_text") or _last_user_text(state)).strip()
        key = text.lower()
        chosen = next((s for s in styles if key in (s["id"].lower(), s["name"].lower())), None)
        if chosen is None and len(key) >= 4:  # "the smart casual one" still finds "Smart Casual"
            chosen = next((s for s in styles if s["name"].lower() in key or key in s["name"].lower()), None)
        update: dict = {}
        if chosen is None:
            # free text, e.g. "something like old-money" or "a grey oversized t-shirt and dark baggy jeans": the planner
            # interprets the look, and what is said about each piece is read now, exactly as in a first message
            chosen = {"id": "custom", "name": text, "description": text}
            try:
                wished = structured(PrefsExtraction, load_prompt("extract_prefs", 3), text)
                update["prefs"] = _merge_prefs(dict(state.get("prefs") or {}), wished)
            except (ValidationError, OutputParserException):
                pass  # the style still works as plain text
        return {"chosen_style": chosen, **update, **_fresh()}

    def restart_plan(state: StylistState):
        return _fresh()  # only the budget changed and a style is already chosen: plan again, skip the style step

    def refine(state: StylistState):
        shown = state.get("shown") or []
        latest = latest_round(shown)
        prefs = dict(state["prefs"])
        context = {"outfits": summarise(latest), "preferences": prefs, "message": _last_user_text(state)}
        edit = structured(RefinementEdit, load_prompt("interpret_refinement"), json.dumps(context))

        anchor = None
        if edit.anchor is not None:
            if not 1 <= edit.anchor <= len(latest):
                reply = f"I showed {len(latest)} outfits in the latest set. Which one did you mean (1 to {len(latest)})?"
                return {"messages": [AIMessage(reply)], "phase": SHOWN}
            outfit = latest[edit.anchor - 1]
            anchor = {"number": edit.anchor, "top": outfit["top"]["title"], "bottom": outfit["bottom"]["title"],
                      "spec": outfit.get("spec")}
        budget = new_budget(int(prefs["budget_inr"]), edit, [o["total_inr"] for o in latest])
        if budget < MIN_BUDGET_INR:
            reply = (f"That is too low for a top and a bottom together. The lowest I can search is "
                     f"₹{MIN_BUDGET_INR}. Want to try that or higher?")
            return {"messages": [AIMessage(reply)], "phase": SHOWN}
        prefs = fold_edit_into_wishes(prefs, edit)  # a change to a piece the shopper fixed replaces that wish
        prefs["budget_inr"] = budget  # a new budget stays; a change to a piece they had not fixed applies to this round only
        return {
            "prefs": prefs, "edit": edit.model_dump(), "anchor": anchor, "proceed": True, "phase": SHOWN,
            "refinements": (state.get("refinements") or []) + [edit.model_dump()], **_fresh(),
        }

    def plan_outfits(state: StylistState):
        existing = state.get("outfits") or []
        need = OUTFITS_WANTED - len(existing)
        prefs = state["prefs"]
        budget = prefs["budget_inr"]
        edit_data, anchor = state.get("edit"), state.get("anchor")
        edit = RefinementEdit.model_validate(edit_data) if edit_data else None
        already = [{"top": o["top"]["title"], "bottom": o["bottom"]["title"]} for o in (state.get("shown") or []) + existing]
        context = {
            "preferences": prefs,
            "chosen_style": state["chosen_style"],
            "outfits_needed": need,
            "already_shown": already,
            "planner_notes": list(state.get("notes") or []),
        }
        if edit:
            context["refinement"] = {
                "anchor": anchor, "relation": edit.relation, "top": edit.top.model_dump() if edit.top else None,
                "bottom": edit.bottom.model_dump() if edit.bottom else None, "note": edit.note, "budget_inr": budget,
            }
        plan = structured(OutfitPlan, load_prompt("plan_outfits", 7), json.dumps(context))
        top_wish, bottom_wish = wish_of(prefs, "top"), wish_of(prefs, "bottom")
        # different garments are the point; one polite re-ask if not. Only for pieces the shopper left open, and not when
        # their wording was a whole-outfit request ("suits") that fixes the garments in a way we could not read as a piece.
        if not edit and (top_wish or bottom_wish or not prefs.get("requests")):
            problems = variety_problems(
                plan.outfits[:need], tops=not (top_wish and top_wish.item), bottoms=not (bottom_wish and bottom_wish.item)
            )
            if problems:
                context["planner_notes"] += problems
                plan = structured(OutfitPlan, load_prompt("plan_outfits", 6), json.dumps(context))
        style = state["chosen_style"] or {}
        specs = apply_wishes([_planner_colours_only(s) for s in plan.outfits[:need]], prefs)
        specs = apply_style_colours(specs, f"{style.get('name', '')} {style.get('description', '')}")
        if edit:
            anchor_spec = OutfitSpec.model_validate(anchor["spec"]) if anchor and anchor.get("spec") else None
            specs = apply_edit(specs, edit, anchor_spec)
        groups = resolve_groups(plan.store_groups, f"{style.get('name', '')} {style.get('description', '')}", prefs.get("requests"))
        specs = [
            with_style(clamp_to_budget(assign_groups(widen_fixed_caps(s, budget), groups), budget), _style_line(style))
            for s in specs
        ]
        return {"outfit_specs": [s.model_dump() for s in specs], "notes": [], "store_groups": groups}

    def find_products(state: StylistState):
        prefs, style = state["prefs"], state.get("chosen_style") or {}
        note = (state.get("edit") or {}).get("note")
        result = find_products_for_specs(
            FindProductsInput(
                specs=[OutfitSpec.model_validate(s) for s in state["outfit_specs"]],
                budget_inr=prefs["budget_inr"],
                exclude_urls=[
                    p["url"] for o in (state.get("shown") or []) + (state.get("outfits") or [])
                    for p in (o["top"], o["bottom"])
                ],
                shopper_words="; ".join(filter(None, [prefs.get("requests"), note])),
                style=_style_line(style),
            ),
            search,
            judge,
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
        errors = state.get("search_errors") or []
        shown = list(state.get("shown") or [])
        round_no = (state.get("round") or 0) + (1 if outfits else 0)
        shown += [{**o, "round": round_no} for o in outfits]
        phase = SHOWN if shown else CHOOSING  # nothing to refine yet: the style cards stay clickable
        done = {"phase": phase, "shown": shown, "round": round_no}

        if not outfits and errors:  # nothing to show because the search itself was unavailable
            reply = "I couldn't search the stores just now: " + " ".join(errors) + " Please try again in a few minutes."
            return {**done, "messages": [AIMessage(reply)]}
        # the outfit cards on screen carry every detail (stores, prices, photos): the text only introduces them
        intro = "Here are {n} new outfits based on your change." if state.get("edit") else (
            f"Here are {{n}} outfits for your {state['chosen_style']['name']} look.")
        lines = [intro.format(n=len(outfits))] if outfits else []
        if len(outfits) < OUTFITS_WANTED:
            if errors:
                lines.append("Some searches were unavailable, so I could only find a few. " + " ".join(errors))
            elif wish_of(state["prefs"], "top") or wish_of(state["prefs"], "bottom"):
                lines.append(
                    f"I could only find {len(outfits)} that match exactly what you asked for. "
                    "Loosen one detail (the colour, the fit or the fabric) or try a higher budget to see more."
                    if outfits else
                    "Nothing in our stores matches exactly what you asked for. Loosen one detail (the colour, the fit or the "
                    "fabric) or try a higher budget."
                )
            else:
                lines.append("I couldn't find all 4 within your budget; try a higher budget or another style.")
        if outfits:
            lines.append("Want changes? Tell me, for example: cheaper, a different top, or more like the 2nd one.")
        return {**done, "messages": [AIMessage("\n".join(lines))]}

    def answer_question(state: StylistState):
        context = {
            "preferences": state.get("prefs") or {}, "outfits": summarise(latest_round(state.get("shown") or [])),
            "question": _last_user_text(state),
        }
        answer = structured(AnswerOut, load_prompt("answer_question"), json.dumps(context))
        return {"messages": [AIMessage(answer.text)]}

    def clarify(state: StylistState):
        phase = state.get("phase")
        if phase == CHOOSING:
            reply = "I didn't quite catch that. Pick one of the styles above, or describe a style you like."
        else:
            reply = ("I can change the outfits for you: ask for something cheaper, a different top or bottom, or "
                     "more like one of them (for example, \"more like the 2nd one\"). Or ask me about any of them.")
        return {"messages": [AIMessage(reply)]}

    # ---- edges -------------------------------------------------------------------------------------------
    def after_route(state: StylistState):
        return _INTENT_TO_NODE[state["intent"]]

    def after_gather(state: StylistState):
        if state["missing"]:
            return "ask_user"
        changed = set(state.get("changed") or [])
        if state.get("intent") == "change_prefs" and state.get("chosen_style") and changed and changed <= {"budget_inr"}:
            return "restart_plan"
        return "propose_styles"

    def after_refine(state: StylistState):
        return "plan_outfits" if state.get("proceed") else END

    def after_validate(state: StylistState):
        # if the search itself was unavailable, replanning cannot help and would only spend more calls
        if state.get("search_errors"):
            return "respond"
        prefs = state["prefs"]
        top, bottom = wish_of(prefs, "top"), wish_of(prefs, "bottom")
        if top and top.item and bottom and bottom.item:
            return "respond"  # the shopper fixed both garments: a new plan would ask for exactly the same products
        if len(state["outfits"]) >= OUTFITS_WANTED or state.get("retries", 0) > MAX_RETRIES:
            return "respond"
        return "plan_outfits"

    g = StateGraph(StylistState)
    for name, fn in [
        ("route_turn", route_turn),
        ("gather_prefs", gather_prefs),
        ("ask_user", ask_user),
        ("propose_styles", propose_styles),
        ("set_style", set_style),
        ("restart_plan", restart_plan),
        ("refine", refine),
        ("plan_outfits", plan_outfits),
        ("find_products", find_products),
        ("rank_and_validate", rank_and_validate),
        ("respond", respond),
        ("answer_question", answer_question),
        ("clarify", clarify),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "route_turn")
    g.add_conditional_edges("route_turn", after_route, sorted(set(_INTENT_TO_NODE.values())))
    g.add_conditional_edges("gather_prefs", after_gather, ["ask_user", "propose_styles", "restart_plan"])
    g.add_edge("ask_user", END)
    g.add_edge("propose_styles", END)
    g.add_edge("set_style", "plan_outfits")
    g.add_edge("restart_plan", "plan_outfits")
    g.add_conditional_edges("refine", after_refine, ["plan_outfits", END])
    g.add_edge("plan_outfits", "find_products")
    g.add_edge("find_products", "rank_and_validate")
    g.add_conditional_edges("rank_and_validate", after_validate, ["plan_outfits", "respond"])
    g.add_edge("respond", END)
    g.add_edge("answer_question", END)
    g.add_edge("clarify", END)
    return g.compile(checkpointer=checkpointer)
