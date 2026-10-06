"""Deterministic self-check: does this product really match what was asked for?

Rules that keep it hallucination-free:
- It only reads data scraped into the Product (title, description, page-stated attributes).
- Each verdict records the evidence it used. With no evidence the status is 'unknown',
  never 'match'.
- price and item are REQUIRED to be 'match'. fit, fabric and category may be 'unknown' but never
  'mismatch'.
- Colour is checked ONLY when the shopper asked for it (spec.color_source 'user'), or the style card they picked
  names it ('style'). The planner's own
  colours are a hidden coordination hint: they steer the search but never reject a product. For a
  shopper-requested colour: it is looked up in the page's colour field, then the title/description; if
  neither states one, it is trusted from the colour-specific search (`assumed`), the report gets
  confidence 'low' and the product ranks below confirmed ones. A stated colour that contradicts the
  request is always rejected.
"""

import re

from api.agent.schemas import AttributeCheck, ItemSpec, MatchReport, Product

_CANON = {
    "tee": "tshirt", "tees": "tshirt", "tshirts": "tshirt",
    "trouser": "pant", "trousers": "pant", "pants": "pant",
    "jeans": "jean", "shorts": "short", "shirts": "shirt", "hoodies": "hoodie",
    "joggers": "jogger", "chinos": "chino", "gray": "grey",
    "cargos": "cargo", "henleys": "henley", "polos": "polo", "overshirts": "overshirt",
    "jackets": "jacket", "sweatshirts": "sweatshirt", "sweaters": "sweater", "kurtas": "kurta",
    "blazers": "blazer",
}
_STOP = {"for", "and", "with", "men", "mens", "women", "womens", "unisex", "the", "a"}
_TOP_WORDS = {
    "tshirt", "shirt", "hoodie", "sweater", "sweatshirt", "kurta", "top", "jacket", "polo",
    "henley", "overshirt", "blazer", "tank",
}
# The garment TYPE. A product must show at least one of the item's garment words; descriptive
# words around it ("crewneck", "slim", "washed") are allowed to be missing from a short title.
_GARMENT_NOUNS = {
    "tshirt", "shirt", "polo", "henley", "hoodie", "sweatshirt", "sweater", "jacket", "kurta",
    "overshirt", "blazer", "tank", "pant", "jean", "short", "jogger", "chino", "legging",
}
_BOTTOM_WORDS = {"pant", "jean", "short", "jogger", "chino", "skirt", "cargo", "legging", "palazzo"}
_COLORS = {
    "red", "blue", "green", "black", "white", "beige", "peach", "pink", "yellow", "grey",
    "brown", "olive", "navy", "maroon", "purple", "orange", "cream", "khaki", "tan", "lavender",
    "mint", "mustard", "teal", "coral", "charcoal",
}
# Stores name the same colour in different words. A requested colour is also met by any of these (tokens as _tokens gives them).
_COLOUR_SYNONYMS = {
    "olive": {"army", "military", "moss"}, "grey": {"slate", "ash"}, "beige": {"sand", "stone", "oatmeal"},
    "maroon": {"burgundy", "wine"}, "brown": {"chocolate", "coffee"}, "white": {"ivory"}, "black": {"jet"},
    "navy": {"midnight"},
}
# What to add to a search for a colour when the plain word finds too little.
_COLOUR_SEARCH_WORDS = {
    "olive": "army green", "grey": "slate grey", "beige": "sand beige", "maroon": "burgundy", "brown": "chocolate brown",
    "navy": "navy blue", "white": "off white",
}


_COLOR_WORDS = _COLORS  # public name for the colour words (the graph reads a style card's colours with it)


def colour_search_words(colour: str | None) -> str | None:
    """Another way stores write this colour, as extra search words ('olive' -> 'army green'), or None."""
    return next((words for c, words in _COLOUR_SEARCH_WORDS.items() if colour and c in colour.lower().split()), None)


def _colour_met(word: str, tokens: list[str]) -> bool:
    return word in tokens or any(s in tokens for s in _COLOUR_SYNONYMS.get(word, ()))


_MALE = {"men", "mens", "man", "male", "gents"}
_FEMALE = {"women", "womens", "woman", "ladies", "female"}
_KIDS = {"boys", "boy", "girls", "girl", "kids", "kid", "junior", "infant"}
_FIT_CONFLICTS = [
    {"oversized", "baggy", "loose", "relaxed", "wide"},
    {"slim", "skinny", "fitted"},
]


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("t-shirt", "tshirt").replace("t shirt", "tshirt")
    return [_CANON.get(t, t) for t in re.findall(r"[a-z0-9]+", text) if t not in _STOP]


def _contains_phrase(hay: list[str], phrase: list[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(hay[i : i + n] == phrase for i in range(len(hay) - n + 1))


def _check_price(p: Product, spec: ItemSpec) -> AttributeCheck:
    ok = p.price_inr <= spec.max_price_inr
    return AttributeCheck(
        attribute="price", requested=f"<= {spec.max_price_inr}", found=str(p.price_inr),
        status="match" if ok else "mismatch", evidence="price field", required=True,
    )


_NECK_WORDS = {"crewneck", "crew", "round", "neck", "v", "vneck"}


def _necks(tokens: list[str]) -> set[str]:
    """Which neckline a title or request names: 'round' (crew/round neck) or 'v' (v-neck)."""
    found = set()
    if "crewneck" in tokens or "crew" in tokens or ("round" in tokens and "neck" in tokens):
        found.add("round")
    if "v" in tokens and "neck" in tokens or "vneck" in tokens:
        found.add("v")
    return found


_PANTS_LIKE = {"pant", "jean", "chino", "jogger", "cargo", "legging", "palazzo", "trackpant", "parachute"}


def _noun_present(noun: str, hay: list[str]) -> bool:
    if noun in hay:
        return True
    if noun == "pant" and "short" not in hay and any(t in hay for t in _PANTS_LIKE):
        return True  # "pants" asked for: jeans, chinos, joggers, cargos and track pants are all pants
    # Stores often call cargo trousers just "Cargos". That counts as pants, but never as shorts.
    return noun == "pant" and "cargo" in hay and "short" not in hay


def _check_item(hay: list[str], spec: ItemSpec) -> AttributeCheck:
    wanted = _tokens(spec.item)
    wanted_neck, title_neck = _necks(wanted), _necks(hay)
    missing = [t for t in wanted if t not in hay and not (t == "pant" and _noun_present("pant", hay))]
    if wanted_neck & title_neck:  # "crewneck" is satisfied by a title saying "Crew Neck"
        missing = [t for t in missing if t not in _NECK_WORDS]
    if not missing:
        return AttributeCheck(
            attribute="item", requested=spec.item, found=spec.item, status="match",
            evidence="all item words found in title/description", required=True,
        )
    if wanted_neck and title_neck and not (wanted_neck & title_neck):  # asked crewneck, got V-neck
        return AttributeCheck(
            attribute="item", requested=spec.item, found=" ".join(sorted(title_neck)) + " neck",
            status="mismatch", evidence="the title names a different neckline", required=True,
        )
    nouns = [t for t in wanted if t in _GARMENT_NOUNS]
    if nouns and any(_noun_present(n, hay) for n in nouns):
        # Right garment, but the title does not repeat every descriptive word. Accept it, flagged
        # as low confidence (same mechanism as an unconfirmed colour), never as a confirmed match.
        return AttributeCheck(
            attribute="item", requested=spec.item, found=" ".join(t for t in wanted if t in hay),
            status="unknown", assumed=True,
            evidence=f"garment type found; the title does not mention: {', '.join(missing)}", required=True,
        )
    return AttributeCheck(
        attribute="item", requested=spec.item, found=None, status="mismatch",
        evidence=f"title/description lacks: {', '.join(missing)}", required=True,
    )


_SET_TITLE = re.compile(r"co-?\s?ords?\b|\bcombo\b|\b(?:set|pair) of\b|\bsuit set\b", re.IGNORECASE)


def _check_category(p: Product, hay: list[str], spec: ItemSpec) -> AttributeCheck:
    own, other = (_TOP_WORDS, _BOTTOM_WORDS) if spec.category == "top" else (_BOTTOM_WORDS, _TOP_WORDS)
    if _SET_TITLE.search(p.title) and any(t in _TOP_WORDS for t in hay) and any(t in _BOTTOM_WORDS for t in hay):
        return AttributeCheck(  # a top AND a bottom sold together is two garments, not the one asked for
            attribute="category", requested=spec.category, found="a set of several garments", status="mismatch",
            evidence="the title names a set (co-ord / combo)", required=False,
        )
    stated = p.attributes.get("category")
    if stated:
        return AttributeCheck(
            attribute="category", requested=spec.category, found=stated,
            status="match" if stated.lower() == spec.category else "mismatch",
            evidence="page category", required=False,
        )
    has_own, has_other = any(t in own for t in hay), any(t in other for t in hay)
    if has_own:
        status, found = "match", spec.category
    elif has_other:
        status, found = "mismatch", "other category"
    else:
        status, found = "unknown", None
    return AttributeCheck(
        attribute="category", requested=spec.category, found=found, status=status,
        evidence="category words in title/description", required=False,
    )


def _check_color(p: Product, hay: list[str], spec: ItemSpec) -> AttributeCheck:
    wanted = _tokens(spec.color)
    stated = p.attributes.get("color") or p.color
    if stated:
        ok = all(_colour_met(t, _tokens(stated)) for t in wanted)
        named = [t for t in hay if t in _COLORS and t not in wanted]
        if ok and named and not all(_colour_met(t, hay) for t in wanted):
            # the page's colour field agrees, but the title the shopper reads names ONLY other colours ("Grey Baggy Parachute
            # Pants" with a field saying Black): the store's own data contradicts itself, so it is not shown as a match
            return AttributeCheck(
                attribute="color", requested=spec.color, found=named[0], status="mismatch",
                evidence="the title names a different colour than the page's colour field", required=True,
            )
        return AttributeCheck(
            attribute="color", requested=spec.color, found=stated,
            status="match" if ok else "mismatch", evidence="page color field", required=True,
        )
    if _contains_phrase(hay, wanted) or all(_colour_met(t, hay) for t in wanted):
        return AttributeCheck(
            attribute="color", requested=spec.color, found=spec.color, status="match",
            evidence="color in title/description", required=True,
        )
    others = [t for t in hay if t in _COLORS and t not in wanted]
    if others:  # the title names a different colour: a contradiction
        return AttributeCheck(
            attribute="color", requested=spec.color, found=others[0], status="mismatch",
            evidence="color words in title/description", required=True,
        )
    # No colour stated anywhere. The search itself was colour-specific, so trust it, but flag it.
    return AttributeCheck(
        attribute="color", requested=spec.color, found=None, status="unknown", assumed=True,
        evidence="colour not stated; trusted from the colour-specific search", required=True,
    )


def _check_avoid(p: Product, spec: ItemSpec) -> AttributeCheck:
    """A colour the shopper does not want, against the colour the PAGE states. (A title that merely mentions the colour,
    such as 'white tee with black print', is left to the judge.)"""
    stated = p.attributes.get("color") or p.color
    unwanted = [_CANON.get(c, c) for c in spec.avoid_colors]
    hits = [t for t in _tokens(stated) if t in unwanted] if stated else []
    return AttributeCheck(
        attribute="avoid", requested="not " + ", ".join(spec.avoid_colors), found=stated,
        status="mismatch" if hits else "match" if stated else "unknown",
        evidence="page colour field" if stated else "colour not stated", required=False,
    )


def _check_gender(p: Product) -> AttributeCheck:
    """The shopper is a man: reject women's and kids' items, accept men's and unisex."""
    stated = p.attributes.get("gender")
    text = stated or f"{p.title} {p.description}"
    words = set(re.findall(r"[a-z]+", text.lower()))
    source = "page gender field" if stated else "title/description"
    if words & _KIDS:
        status, found = "mismatch", "kids"
    elif "unisex" in words or (words & _MALE and words & _FEMALE):
        status, found = "match", "unisex"
    elif words & _MALE:
        status, found = "match", "men"
    elif words & _FEMALE:
        status, found = "mismatch", "women"
    else:
        status, found = "unknown", None
    return AttributeCheck(
        attribute="gender", requested="men", found=found, status=status,
        evidence=source, required=False,
    )


def _check_soft(attr: str, requested: str, p: Product, hay: list[str]) -> AttributeCheck:
    wanted = _tokens(requested)
    stated = p.attributes.get(attr)
    pool = _tokens(stated) if stated else hay
    if attr == "fabric" and "denim" in wanted and "jean" in hay:
        pool = pool + ["denim"]  # jeans are denim: a title that says "Jeans" confirms it
    if attr == "fabric" and stated:
        # a page's material field names the base fibre ("Cotton") while the title names the fabric ("Denim Baggy Jeans"):
        # either one confirms the fabric the shopper asked for
        pool = pool + hay
    source = "page field" if stated else "title/description"
    if all(t in pool for t in wanted):
        return AttributeCheck(
            attribute=attr, requested=requested, found=stated or requested, status="match",
            evidence=f"{attr} in {source}", required=False,
        )
    if attr == "fit":
        want_group = next((g for g in _FIT_CONFLICTS if set(wanted) & g), None)
        clash = [t for g in _FIT_CONFLICTS if g is not want_group for t in pool if t in g]
        if want_group and clash:
            return AttributeCheck(
                attribute=attr, requested=requested, found=clash[0], status="mismatch",
                evidence="conflicting fit word", required=False,
            )
    if stated:
        return AttributeCheck(
            attribute=attr, requested=requested, found=stated, status="mismatch",
            evidence="page field", required=False,
        )
    return AttributeCheck(
        attribute=attr, requested=requested, found=None, status="unknown",
        evidence="not stated on the page", required=False,
    )


def verify_product(product: Product, spec: ItemSpec) -> MatchReport:
    hay = _tokens(f"{product.title} {product.description}")
    checks = [
        _check_price(product, spec),
        _check_item(hay, spec),
        _check_category(product, hay, spec),
        _check_gender(product),
    ]
    if spec.color and spec.color_source in ("user", "style"):
        checks.insert(3, _check_color(product, hay, spec))
    if spec.avoid_colors:
        checks.append(_check_avoid(product, spec))
    if spec.fit:
        checks.append(_check_soft("fit", spec.fit, product, hay))
    if spec.fabric:
        checks.append(_check_soft("fabric", spec.fabric, product, hay))

    blocking = [
        c.attribute
        for c in checks
        # a contradiction always blocks; a required attribute with no evidence blocks unless it
        # is an assumed one (colour trusted from the search)
        if (c.status == "mismatch" and c.attribute not in spec.loose)
        or (c.required and c.status != "match" and not c.assumed)
    ]
    matched = sum(c.status == "match" for c in checks)
    return MatchReport(
        is_match=not blocking,
        confidence="low" if any(c.assumed for c in checks) else "high",
        score=round(matched / len(checks), 2),
        checks=checks,
        blocking=blocking,
    )
