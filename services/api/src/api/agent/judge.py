"""The reader: a model reads the real candidate products and judges them against what the shopper asked for.

Why it exists: the rule-based verifier (verify.py) is exact about price, garment and men's wear, but it cannot read like a
person. A page titled "Cloud Tee, relaxed fit" that never says "white" in its data is a white tee in the photo, and the
verifier can only call its colour unknown. The reader fills that gap, the way a person scanning the results would.

What keeps it safe (nothing can be invented):
  - It only sees products that are already real (read from the store's own page) and already passed the verifier.
  - It can only KEEP or DROP a candidate and say why. It never supplies a price, a link, a stock status or a product.
  - If the model fails or answers badly, the search carries on with the rule-based result alone.
"""

import json
import logging
import re
from collections.abc import Callable
from urllib.parse import urlparse

from api.agent.prompts import load_prompt
from api.agent.schemas import ItemSpec, JudgeResult, Product

log = logging.getLogger(__name__)

# judge(spec, candidates, shopper_words, style, needed) -> verdicts for those candidates
Judge = Callable[[ItemSpec, list[Product], str, str, int], JudgeResult]


def link_words(url: str) -> str:
    """The product page's address often names the product ('/products/white-oversized-tee'): useful evidence."""
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", slug).split())[:90]


def wanted_by_shopper(spec: ItemSpec) -> dict:
    """What the shopper fixed for this piece (the garment is always required), apart from the planner's own choices."""
    required = {"item": spec.item}
    for attr in ("color", "fit", "fabric"):
        value = getattr(spec, attr)
        if value and (attr in spec.fixed or (attr == "color" and spec.color_source == "user")):
            required[attr] = value
    return required


def planner_hints(spec: ItemSpec, required: dict) -> dict:
    return {a: getattr(spec, a) for a in ("color", "fit", "fabric") if getattr(spec, a) and a not in required}


def describe(number: int, p: Product) -> dict:
    """One candidate as the reader sees it: only facts the store's own page stated."""
    return {
        "number": number, "title": p.title, "store": p.retailer, "price_inr": p.price_inr,
        "colour_stated_by_page": p.attributes.get("color") or p.color,
        "fabric_stated_by_page": p.attributes.get("fabric"),
        "search_snippet": p.description[:300], "page_description": p.details[:500], "link_words": link_words(p.url),
    }


def make_judge(structured: Callable) -> Judge:
    """A judge that asks the model (`structured(schema, system, human)`, the graph's own model call)."""

    def judge(spec: ItemSpec, candidates: list[Product], shopper_words: str, style: str, needed: int) -> JudgeResult:
        required = wanted_by_shopper(spec)
        context = {
            "shopper_words": shopper_words, "style": style, "required": required,
            "planner_hints_not_required": planner_hints(spec, required), "avoid_colours": spec.avoid_colors,
            "products_needed": needed, "candidates": [describe(i, p) for i, p in enumerate(candidates, 1)],
        }
        return structured(JudgeResult, load_prompt("judge_products"), json.dumps(context))

    return judge


def safe_judge(judge: Judge, spec: ItemSpec, candidates: list[Product], shopper_words: str, style: str, needed: int):
    """(verdicts by candidate url, retry keywords). A model failure means no verdicts: the rule-based result stands."""
    try:
        result = judge(spec, candidates, shopper_words, style, needed)
    except Exception as exc:  # noqa: BLE001  the model is down, slow or unreadable: never let the reader break a search
        log.warning("the product reader failed (%s: %s); using the rule-based check alone", type(exc).__name__, str(exc)[:120])
        return {}, None
    by_number = {v.number: v for v in result.verdicts}
    verdicts = {}
    for i, product in enumerate(candidates, 1):
        v = by_number.get(i)
        verdicts[product.url] = (v.fits, v.reason) if v else ("unsure", "")  # not mentioned: neither kept nor dropped
    return verdicts, (result.retry_keywords or "").strip() or None
