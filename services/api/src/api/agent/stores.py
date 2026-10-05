"""Which groups of stores to search, once the shopper has picked a style.

The tool server holds the approved sellers (100 menswear brands) in five groups. One search covers every store in
the chosen groups, so searching fewer, better groups gives better results for the same single credit.

Who decides:
  - the PLANNER (a model) chooses the groups for the look, from the guide below, because it knows the style;
  - CODE adds a group a garment obviously needs (a kurta is only sold by the traditional stores, jeans by the denim
    ones), so a forgetful or wrong model can never leave a garment with no store that sells it;
  - CODE falls back to a sensible default from the style's words if the model chose nothing valid.
"""

import re

GROUPS = ("streetwear", "smart_casual", "denim", "traditional", "activewear")  # the same ids the tool server uses

GROUP_GUIDE = {
    "streetwear": "Gen-Z and streetwear D2C brands: graphic and oversized tees, hoodies, cargos, joggers (Snitch, "
                  "Bewakoof, The Souled Store, Urban Monkey, Wrogn, Beyoung...)",
    "smart_casual": "Smart casual, shirts, linen, formal and premium labels incl. global labels sold in India (Rare "
                    "Rabbit, Andamen, The Bear House, Allen Solly, US Polo, Jack & Jones, Levi's...)",
    "denim": "Denim specialists: jeans and denim casuals (Spykar, Killer, Pepe, Wrangler, Mufti...)",
    "traditional": "Traditional, ethnic, handloom and sustainable: kurtas, sherwanis, nehru jackets, linen/khadi "
                   "(Manyavar, Fabindia, Utsav Fashion, Nicobar...)",
    "activewear": "Innerwear, loungewear, activewear and outdoor (Puma, Decathlon, Damensch, Jockey...)",
}

MAX_GROUPS = 3  # beyond this a search is spread too thin to be better than just searching everything


def clean_groups(groups) -> list[str]:
    """Only valid group ids, no repeats, in the canonical order."""
    wanted = {str(g).strip().lower() for g in groups or []}
    return [g for g in GROUPS if g in wanted]


_STYLE_HINTS = [
    (re.compile(r"ethnic|tradition|wedding|festiv|kurta|indo|sherwani|desi|mehendi|sangeet|puja|diwali|eid|handloom|khadi"), ["traditional", "smart_casual"]),
    (re.compile(r"denim|jean"), ["denim", "streetwear"]),
    (re.compile(r"sport|athleisure|gym|active|track|lounge"), ["streetwear", "activewear"]),
    (re.compile(r"street|hip.?hop|urban|oversize|gen.?z|korean|grunge|retro|skate|y2k|baggy|cargo|graphic"), ["streetwear"]),
    (re.compile(r"smart|office|formal|business|interview|minimal|linen|preppy|old.?money|classic|elegant|suit|blazer|reunion|date|dinner|clean"), ["smart_casual"]),
]


def default_groups(style_text: str, requests: str | None = None) -> list[str]:
    """A sensible choice when the planner gave none: read the style's words, else streetwear + smart casual."""
    text = f"{style_text} {requests or ''}".lower()
    for pattern, groups in _STYLE_HINTS:
        if pattern.search(text):
            return groups
    return ["streetwear", "smart_casual"]


_ITEM_NEEDS = [
    (re.compile(r"\b(jeans?|denim)\b"), "denim"),
    (re.compile(r"kurta|sherwani|nehru|bandhgala|dhoti|veshti|pyjama|churidar|achkan|jodhpuri|angrakha|mundu"), "traditional"),
    (re.compile(r"jogger|track ?pants?|trackpants?|sweatpants?|gym|sports?|athletic|dry.?fit|compression"), "activewear"),
]


def groups_for_item(item: str, planned: list[str]) -> list[str]:
    """The groups to search for ONE garment: the planned groups, plus any the garment needs."""
    groups = set(planned)
    text = item.lower()
    for pattern, group in _ITEM_NEEDS:
        if pattern.search(text):
            groups.add(group)
    return [g for g in GROUPS if g in groups]


def specialist_groups(item: str) -> list[str]:
    """The groups that SPECIALISE in this garment (jeans: the denim stores), or [] when no group does. A search over only
    those stores is not diluted by pages from stores that sell a little of everything."""
    return groups_for_item(item, [])


_GENERAL_GROUPS = ("streetwear", "smart_casual", "activewear")  # stores that sell everyday garments of any kind


def second_try_groups(item: str, tried: list[list[str]]) -> list[str]:
    """Where to look when the searches so far found too few fits (`tried`: the group lists already searched). First the
    stores that specialise in the garment, narrowing a wide search; then the everyday-clothing groups not yet covered.
    A group list that was already searched is never offered again. [] = nothing new to try (or every store was searched)."""
    if not any(tried):  # the first search had no group list: it already covered every store
        return []
    covered = {g for t in tried for g in t}
    options = [specialist_groups(item), [g for g in _GENERAL_GROUPS if g not in covered]]
    done = [sorted(t) for t in tried]
    return next((opt for opt in options if opt and sorted(opt) not in done), [])


def resolve_groups(planned, style_text: str, requests: str | None = None) -> list[str]:
    """The planner's valid groups (capped), else a default from the style."""
    chosen = clean_groups(planned)[:MAX_GROUPS]
    return chosen or default_groups(style_text, requests)
