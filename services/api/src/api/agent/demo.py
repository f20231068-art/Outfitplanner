"""Demo mode: a deterministic stand-in for the chat model, used with the mock product search.

Why it exists: the free chat model allows only ~8 conversations a day, and evals, tracing and
dashboards need many runs. Demo mode lets the whole pipeline (API, streaming, database, audit, traces,
metrics, scorers) run offline, instantly and for free. It is NOT a quality test of the real model:
it plans from fixed lists, so it can only test the plumbing and the verifier, never the model's taste.

The API refuses to start in demo mode when ENVIRONMENT=prod.
"""

import json
import os
import re
import time

from api.agent.schemas import (
    AnswerOut,
    CandidateVerdict,
    GarmentWish,
    ItemSpec,
    JudgeResult,
    OutfitPlan,
    OutfitSpec,
    PrefsExtraction,
    RefinementEdit,
    SlotEdit,
    StyleList,
    StyleOption,
    TurnIntent,
)
from api.agent.verify import _COLORS

STYLES = [
    ("streetwear", "Streetwear", "Oversized tees with relaxed cargos and chunky sneakers"),
    ("smart-casual", "Smart Casual", "Crisp shirts with slim chinos for a polished everyday look"),
    ("minimalist", "Minimalist", "Solid neutrals and clean lines, nothing loud"),
    ("korean-casual", "Korean Casual", "Soft pastels, layered tops and wide-leg trousers"),
    ("sporty", "Retro Sporty", "Track-inspired pieces with comfortable joggers"),
]
# (garment, colour, fit). Distinct garments across outfits are what the variety scorer looks for.
TOPS = [
    ("t-shirt", "white", "oversized"), ("polo shirt", "navy blue", None), ("henley", "olive green", None),
    ("shirt", "sky blue", "slim"), ("hoodie", "grey", None), ("sweatshirt", "black", None),
]
BOTTOMS = [
    ("jeans", "black", "slim"), ("chinos", "beige", None), ("joggers", "charcoal grey", None),
    ("cargo pants", "olive green", None), ("trousers", "navy blue", "slim"),
]
OCCASIONS = ["college", "office", "party", "wedding", "casual", "gym", "date", "travel", "interview", "festival"]


def _human_text(messages) -> str:
    return " ".join(str(m.content) for m in messages if getattr(m, "type", "") == "human")


def _last_human_text(messages) -> str:
    texts = [str(m.content) for m in messages if getattr(m, "type", "") == "human"]
    return texts[-1] if texts else ""


_ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}
_BOTTOM_HINTS = ("bottom", "pant", "trouser", "jean", "chino", "jogger", "cargo")
_REFINE_WORDS = ("cheaper", "cheap", "less expensive", "pricier", "expensive", "spend more", "more like", "similar",
                 "like the", "like outfit", "different", "another", "other", "swap", "change", "instead", "replace",
                 "make the", "show me")
_QUESTION_START = ("why", "what", "which", "how", "is ", "are ", "does", "do ", "can ", "will ")


def parse_anchor(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"outfit\s*(\d)", t) or re.search(r"\b(\d)(?:st|nd|rd|th)\b", t)
    if m:
        return int(m.group(1))
    if "last one" in t:
        return 4
    return next((n for w, n in _ORDINALS.items() if w in t), None)


def parse_refinement(text: str) -> RefinementEdit:
    """Keyword reading of a change request: enough to drive the whole pipeline offline."""
    t = text.lower()
    colour = next((c for c in sorted(_COLORS) if re.search(rf"\b{c}\b", t)), None)
    on_bottom = any(h in t for h in _BOTTOM_HINTS)
    slot = SlotEdit(color=colour) if colour else None
    cheaper = any(w in t for w in ("cheaper", "cheap", "less expensive", "lower price"))
    relation = "more_like" if ("more like" in t or "similar" in t or parse_anchor(t)) else (
        "replace" if any(w in t for w in ("different", "another", "other", "instead")) else "tweak")
    return RefinementEdit(
        anchor=parse_anchor(t), relation=relation,
        top=slot if slot and not on_bottom else None, bottom=slot if slot and on_bottom else None,
        budget_inr=parse_budget(t), cheaper=cheaper and not parse_budget(t),
        pricier=(not cheaper) and any(w in t for w in ("expensive", "pricier", "spend more", "premium")),
    )


def parse_budget(text: str) -> int | None:
    """'around 4000 rupees', '₹4,000', 'under 4k' -> 4000. Small numbers without 'k' are not budgets."""
    for m in re.finditer(r"(\d[\d,]*\.?\d*)\s*(k)?\b", text.lower()):
        n = float(m.group(1).replace(",", ""))
        value = int(n * 1000) if m.group(2) else int(n)
        if value >= 300:
            return value
    return None


_TOP_ITEMS = ("t-shirt", "tshirt", "polo", "henley", "hoodie", "sweatshirt", "shirt", "kurta", "jacket")
_BOTTOM_ITEMS = ("jeans", "chinos", "joggers", "trousers", "cargo pants", "shorts", "pants")
_FITS = ("oversized", "baggy", "slim", "relaxed", "loose", "wide")
_FABRICS = ("denim", "linen", "cotton", "corduroy")


def _piece(clause: str, items: tuple[str, ...]) -> GarmentWish | None:
    item = next((i for i in items if re.search(rf"\b{re.escape(i)}\b", clause)), None)
    if not item:
        return None
    colour = next((c for c in sorted(_COLORS) if re.search(rf"\b{c}\b", clause)), None)
    return GarmentWish(
        item="t-shirt" if item == "tshirt" else item, color=colour,
        fit=next((f for f in _FITS if f in clause), None), fabric=next((f for f in _FABRICS if f in clause), None),
    )


def parse_wishes(text: str) -> tuple[GarmentWish | None, GarmentWish | None]:
    """Keyword reading of 'a white oversized tshirt and denim baggy jeans': each colour belongs to the garment it is next to."""
    top = bottom = None
    for clause in re.split(r",|\band\b|\bwith\b|\+", text.lower()):
        top = top or _piece(clause, _TOP_ITEMS)
        bottom = bottom or _piece(clause, _BOTTOM_ITEMS)
    return top, bottom


def parse_occasion(text: str) -> str | None:
    return next((o for o in OCCASIONS if o in text.lower()), None)


class ScriptedLLM:
    """Same surface the graph uses from a LangChain chat model: `with_structured_output(...)`."""

    model_name = "demo-scripted"

    def with_structured_output(self, schema, **_kwargs):
        return _Runner(schema)


class _Runner:
    def __init__(self, schema):
        self.schema = schema

    def invoke(self, messages):
        if self.schema is PrefsExtraction:
            last, text = _last_human_text(messages), _human_text(messages)
            # the shopper's latest words win when they change their mind
            top, bottom = parse_wishes(text)
            avoid = [c for c in sorted(_COLORS) if re.search(rf"\b(?:no|not|avoid|without)\s+{c}\b", text.lower())]
            return PrefsExtraction(
                budget_inr=parse_budget(last) or parse_budget(text),
                occasion=parse_occasion(last) or parse_occasion(text),
                requests="suits" if "suit" in text.lower() else (text if (top or bottom) else None),
                top=top, bottom=bottom, avoid=avoid or None,
            )
        if self.schema is JudgeResult:  # demo: every real candidate that passed the rule-based check fits
            ctx = json.loads(messages[-1].content)
            return JudgeResult(verdicts=[CandidateVerdict(number=c["number"], fits="yes", reason="demo") for c in ctx["candidates"]])
        if self.schema is TurnIntent:
            return self._intent(json.loads(messages[-1].content))
        if self.schema is RefinementEdit:
            return parse_refinement(json.loads(messages[-1].content)["message"])
        if self.schema is AnswerOut:
            ctx = json.loads(messages[-1].content)
            first = (ctx.get("outfits") or [{}])[0]
            detail = f" Outfit 1 is {first['top']} with {first['bottom']} for ₹{first['total_inr']}." if first else ""
            return AnswerOut(text="These are matched to your budget and style." + detail + " Ask me for changes any time.")
        if self.schema is StyleList:
            return StyleList(
                styles=[StyleOption(id=i, name=n, description=d, image_prompt=f"flat-lay of {n.lower()} menswear")
                        for i, n, d in STYLES]
            )
        if self.schema is OutfitPlan:
            # demo only: make planning slow, to reproduce a real turn's length (a model call plus store searches
            # takes 1-2 minutes) without spending any model quota, e.g. DEMO_PLAN_DELAY_S=70
            time.sleep(float(os.environ.get("DEMO_PLAN_DELAY_S", "0") or 0))
            return self._plan(json.loads(messages[-1].content))
        raise AssertionError(f"demo mode cannot answer {self.schema}")

    @staticmethod
    def _intent(ctx: dict) -> TurnIntent:
        text, listed, shown = ctx["message"].lower(), [s.lower() for s in ctx["styles_listed"]], ctx["outfits_shown"]
        named = next((s for s in STYLES if s[1].lower() in text or s[0] in text), None)
        if any(p in text for p in ("more styles", "other styles", "different styles", "another style")):
            return TurnIntent(intent="more_styles")
        if named and (listed or ctx["phase"] == "outfits_shown"):
            return TurnIntent(intent="choose_style", style=named[1])
        if shown and any(w in text for w in _REFINE_WORDS):
            return TurnIntent(intent="refine")
        if "?" in text or text.startswith(_QUESTION_START):
            return TurnIntent(intent="question")
        if parse_occasion(text) or parse_budget(text):
            return TurnIntent(intent="change_prefs")
        if ctx["phase"] == "choosing_style":
            return TurnIntent(intent="choose_style", style=ctx["message"])
        return TurnIntent(intent="unclear")

    @staticmethod
    def _plan(context: dict) -> OutfitPlan:
        budget = int(context["preferences"]["budget_inr"])
        need = int(context["outfits_needed"])
        style_id = (context.get("chosen_style") or {}).get("id", "custom")
        # different styles, and each later round, start from different pieces
        offset = (sum(map(ord, style_id)) + len(context.get("already_shown") or [])) % len(TOPS)
        total = int(budget * 0.85)  # leave a little room under the budget
        top_cap, bottom_cap = int(total * 0.4 // 10 * 10), int(total * 0.6 // 10 * 10)
        outfits = []
        for i in range(need):
            top, bottom = TOPS[(offset + i) % len(TOPS)], BOTTOMS[(offset * 2 + i) % len(BOTTOMS)]
            outfits.append(OutfitSpec(
                top=ItemSpec(category="top", item=top[0], color=top[1], fit=top[2], max_price_inr=top_cap),
                bottom=ItemSpec(category="bottom", item=bottom[0], color=bottom[1], fit=bottom[2], max_price_inr=bottom_cap),
                rationale=f"A {top[0]} with {bottom[0]}: a balanced {style_id.replace('-', ' ')} look.",
            ))
        groups = {"sporty": ["streetwear", "activewear"], "streetwear": ["streetwear"], "korean-casual": ["streetwear"],
                  "smart-casual": ["smart_casual"], "minimalist": ["smart_casual"]}.get(style_id, ["streetwear", "smart_casual"])
        return OutfitPlan(outfits=outfits, store_groups=groups)
