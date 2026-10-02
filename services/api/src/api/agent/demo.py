"""Demo mode: a deterministic stand-in for the chat model, used with the mock product search.

Why it exists: the free chat model allows only ~8 conversations a day, and evals, tracing and
dashboards need many runs. Demo mode lets the whole pipeline (API, streaming, database, audit, traces,
metrics, scorers) run offline, instantly and for free. It is NOT a quality test of the real model:
it plans from fixed lists, so it can only test the plumbing and the verifier, never the model's taste.

The API refuses to start in demo mode when ENVIRONMENT=prod.
"""

import json
import re

from api.agent.schemas import (
    ItemSpec,
    OutfitPlan,
    OutfitSpec,
    PrefsExtraction,
    StyleList,
    StyleOption,
)

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


def parse_budget(text: str) -> int | None:
    """'around 4000 rupees', '₹4,000', 'under 4k' -> 4000. Small numbers without 'k' are not budgets."""
    for m in re.finditer(r"(\d[\d,]*\.?\d*)\s*(k)?\b", text.lower()):
        n = float(m.group(1).replace(",", ""))
        value = int(n * 1000) if m.group(2) else int(n)
        if value >= 300:
            return value
    return None


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
            text = _human_text(messages)
            return PrefsExtraction(budget_inr=parse_budget(text), occasion=parse_occasion(text))
        if self.schema is StyleList:
            return StyleList(
                styles=[StyleOption(id=i, name=n, description=d, image_prompt=f"flat-lay of {n.lower()} menswear")
                        for i, n, d in STYLES]
            )
        if self.schema is OutfitPlan:
            return self._plan(json.loads(messages[-1].content))
        raise AssertionError(f"demo mode cannot answer {self.schema}")

    @staticmethod
    def _plan(context: dict) -> OutfitPlan:
        budget = int(context["preferences"]["budget_inr"])
        need = int(context["outfits_needed"])
        style_id = (context.get("chosen_style") or {}).get("id", "custom")
        offset = sum(map(ord, style_id)) % len(TOPS)  # different styles start from different pieces
        total = int(budget * 0.85)  # leave a little room under the budget
        top_cap, bottom_cap = int(total * 0.4 // 10 * 10), int(total * 0.6 // 10 * 10)
        outfits = []
        for i in range(need):
            top, bottom = TOPS[(offset + i) % len(TOPS)], BOTTOMS[(offset * 2 + i) % len(BOTTOMS)]
            outfits.append(OutfitSpec(
                top=ItemSpec(category="top", item=top[0], color=top[1], fit=top[2], max_price_inr=top_cap),
                bottom=ItemSpec(category="bottom", item=bottom[0], color=bottom[1], fit=bottom[2], max_price_inr=bottom_cap),
                rationale=f"{top[1].title()} {top[0]} with {bottom[1]} {bottom[0]}: a balanced {style_id.replace('-', ' ')} look.",
            ))
        return OutfitPlan(outfits=outfits)
