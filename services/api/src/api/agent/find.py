"""find_products: typed input -> search -> verify every candidate -> (optionally) a model reads the survivors -> typed output.

Only candidates whose verification says `is_match` can end up in an outfit. Everything rejected is
returned with the reasons, so a wrong result is visible rather than silently shown to the user.

The reader (judge.py) comes after the rule-based verifier and can only drop or prefer products that already passed it.
When too few products fit, it suggests extra search words and the search is repeated once (`judge_search_retries`).
Pieces that ask for the same thing (the shopper fixed "a white oversized t-shirt" for all four outfits) share one search
and one reading, and the four outfits then take the best, second best... product in turn.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from api.agent.judge import Judge, safe_judge
from api.agent.products import ProductSearch, SearchUnavailable
from api.agent.schemas import (
    FindProductsInput,
    FindProductsOutput,
    ItemSpec,
    Outfit,
    Product,
    RejectedCandidate,
    UnfilledSpec,
)
from api.agent.stores import second_try_groups
from api.agent.verify import colour_search_words, verify_product
from api.config import settings

log = logging.getLogger(__name__)

Verdicts = dict[str, tuple[str, str]]  # product url -> (yes | no | unsure, the reader's one-line reason)


def _reasons(product: Product) -> list[str]:
    report = product.verification
    assert report is not None
    return [
        f"{c.attribute}: asked '{c.requested}', found '{c.found}' ({c.status})"
        for c in report.checks
        if c.attribute in report.blocking
    ]


def _rank_key(p: Product, verdicts: Verdicts):
    # the reader's "yes" first, then confirmed attributes, then a higher match score, then how relevant the search said the
    # page is (to the nearest 0.1, so near-ties fall through), then a higher price (more of the budget, under the cap)
    return (
        verdicts.get(p.url, ("", ""))[0] == "yes",
        p.verification.confidence == "high",  # type: ignore[union-attr]
        p.verification.score,  # type: ignore[union-attr]
        round(p.relevance or 0, 1),
        p.price_inr,
    )


def _verified_ranked(
    hits: list[Product], spec: ItemSpec, used_urls: set[str], rejected: list[RejectedCandidate],
    verdicts: Verdicts | None = None,
) -> list[Product]:
    """Verify each hit; keep matches, record the rest. Best first: the reader's pick, then highest match score, then price."""
    verdicts = verdicts or {}
    verified: list[Product] = []
    for hit in hits:
        reasons: list[str] = []
        checked = hit.model_copy(update={"verification": verify_product(hit, spec)})
        if not checked.verification.is_match:  # type: ignore[union-attr]
            reasons = _reasons(checked)
        elif hit.in_stock is False:
            reasons = ["availability: out of stock"]
        elif verdicts.get(hit.url, ("", ""))[0] == "no":
            reasons = [f"reader: {verdicts[hit.url][1] or 'does not fit what was asked'}"]
        elif hit.url in used_urls or _look_of(hit) in used_urls:
            reasons = ["duplicate: already used in another outfit"]

        if reasons:
            rejected.append(
                RejectedCandidate(title=hit.title, retailer=hit.retailer, url=hit.url, reasons=reasons)
            )
        else:
            if verdicts.get(hit.url, ("", ""))[0] == "unsure":  # the reader could not confirm it: shown, but flagged
                checked = checked.model_copy(
                    update={"verification": checked.verification.model_copy(update={"confidence": "low"})}  # type: ignore[union-attr]
                )
            verified.append(checked)
    return sorted(verified, key=lambda p: _rank_key(p, verdicts), reverse=True)


def _best_verified(
    hits: list[Product], spec: ItemSpec, used_urls: set[str], rejected: list[RejectedCandidate],
    verdicts: Verdicts | None = None,
) -> Product | None:
    ranked = _verified_ranked(hits, spec, used_urls, rejected, verdicts)
    return ranked[0] if ranked else None


PAIRS_TRIED = 6  # how many of the best tops and bottoms are tried together when the very best pair is over the budget


def _pair_within(tops: list[Product], bottoms: list[Product], budget: int) -> tuple[Product, Product] | None:
    """The best top with the best bottom that still fits the budget together. Each piece is ranked on its own, so the
    two best can be over budget while the best top and the next bottom are not."""
    for top in tops[:PAIRS_TRIED]:
        for bottom in bottoms[:PAIRS_TRIED]:
            if top.price_inr + bottom.price_inr <= budget:
                return top, bottom
    return None


def _look_of(p: Product) -> str:
    """Stores list one design under several links (a colour or size each). The same store, title and photo is the same look
    on screen, so two outfits must not both use it."""
    return f"{p.retailer.lower()}|{p.title.lower()}|{p.image_url}"


def _group_key(spec: ItemSpec) -> tuple:
    """Pieces with the same key ask the search for exactly the same thing (the price cap is applied afterwards)."""
    return (
        spec.category, spec.item.lower(), (spec.color or "").lower(), spec.color_source, (spec.fit or "").lower(),
        (spec.fabric or "").lower(), spec.keywords or "", tuple(spec.store_groups), tuple(spec.avoid_colors),
    )


def _wants_reader(spec: ItemSpec, inp: FindProductsInput) -> bool:
    """The reader is worth a model call when the shopper asked for something specific; for a purely planner-chosen piece
    the rule-based check is enough."""
    return bool(inp.shopper_words or spec.fixed or spec.avoid_colors or spec.color_source in ("user", "style"))


def find_products_for_specs(inp: FindProductsInput, search: ProductSearch, judge: Judge | None = None) -> FindProductsOutput:
    specs = inp.specs
    items = [s.top for s in specs] + [s.bottom for s in specs]
    errors: list[str] = []

    def safe_search(spec: ItemSpec) -> list[Product]:
        try:
            return search(spec)
        except SearchUnavailable as exc:  # one failed search must not crash the whole conversation
            errors.append(str(exc))
            return []

    def usable(hit: Product, spec: ItemSpec) -> bool:
        return hit.in_stock is not False and verify_product(hit, spec).is_match

    def work(group: list[ItemSpec]) -> tuple[list[Product], Verdicts]:
        """One search for a group of identical pieces, then (if worthwhile) the reader, then at most one more search."""
        lead = group[0].model_copy(update={"max_price_inr": max(s.max_price_inr for s in group)})
        verdicts: Verdicts = {}
        hits = safe_search(lead)
        if judge is None or not _wants_reader(lead, inp):
            return hits, verdicts
        tried = [list(lead.store_groups)]  # the group lists searched so far (a retry never repeats one)
        needed = len(group)  # how many different products the outfits need from this search
        words_tried: set[str] = set()
        for attempt in range(1 + max(0, settings.judge_search_retries)):
            fresh = [h for h in hits if h.url not in verdicts and usable(h, lead)]
            fresh = [h.model_copy(update={"verification": verify_product(h, lead)}) for h in fresh]
            fresh.sort(key=lambda p: _rank_key(p, {}), reverse=True)
            keywords = None
            if fresh:
                new, keywords = safe_judge(
                    judge, lead, fresh[: settings.judge_max_candidates], inp.shopper_words, inp.style, needed
                )
                verdicts.update(new)
            yes = sum(v[0] == "yes" for v in verdicts.values())
            elsewhere = second_try_groups(lead.item, tried)
            log.info(
                "reader: %s '%s' attempt %d: %d yes of %d read, %d needed; next try: groups=%s keywords=%r",
                lead.category, lead.item, attempt + 1, yes, len(verdicts), needed, elsewhere, keywords,
            )
            if yes >= needed or attempt >= settings.judge_search_retries:
                break
            # A second search, aimed better: the reader's own words, and other stores (the specialists in the garment, or the
            # everyday-clothing stores the first search did not cover). One search gives each store only a thin share of its
            # 20 results, so a different set of stores finds different products.
            if not keywords and lead.color_source in ("user", "style"):
                keywords = colour_search_words(lead.color)  # no words from the reader: another way stores name the colour
            if keywords in words_tried:
                keywords = None
            if not keywords and not elsewhere:
                break
            words_tried.add(keywords or "")
            retry_groups = elsewhere or []  # nowhere new to look: the same words over every store
            tried.append(retry_groups)
            more = safe_search(lead.model_copy(update={"keywords": keywords, "store_groups": retry_groups}))
            seen = {h.url for h in hits}
            hits += [h for h in more if h.url not in seen]
        return hits, verdicts

    groups: dict[tuple, list[ItemSpec]] = {}
    for it in items:
        groups.setdefault(_group_key(it), []).append(it)
    with ThreadPoolExecutor(max_workers=8) as pool:  # all searches (and readings) in parallel
        keys = list(groups)
        found = dict(zip(keys, pool.map(lambda k: work(groups[k]), keys), strict=True))

    used_urls = set(inp.exclude_urls)
    outfits: list[Outfit] = []
    unfilled: list[UnfilledSpec] = []
    rejected: list[RejectedCandidate] = []
    for i, spec in enumerate(specs):
        top_hits, top_verdicts = found[_group_key(spec.top)]
        bottom_hits, bottom_verdicts = found[_group_key(spec.bottom)]
        tops = _verified_ranked(top_hits, spec.top, used_urls, rejected, top_verdicts)
        bottoms = _verified_ranked(bottom_hits, spec.bottom, used_urls, rejected, bottom_verdicts)
        top, bottom = tops[0] if tops else None, bottoms[0] if bottoms else None
        pair = _pair_within(tops, bottoms, inp.budget_inr)
        if pair:
            top, bottom = pair
            used_urls |= {top.url, bottom.url, _look_of(top), _look_of(bottom)}  # only reserve products that made it into an outfit
            low = "low" in (top.verification.confidence, bottom.verification.confidence)  # type: ignore[union-attr]
            outfits.append(
                Outfit(
                    top=top, bottom=bottom, rationale=spec.rationale, spec=spec,
                    total_inr=top.price_inr + bottom.price_inr,
                    confidence="low" if low else "high",
                )
            )
            continue
        missing = spec.top if not top else spec.bottom if not bottom else None
        if missing:
            reason = f"no verified match for '{' '.join(filter(None, [missing.color, missing.item]))}'"
        else:
            reason = "verified items exceed the total budget together"
        unfilled.append(
            UnfilledSpec(spec_index=i, item=f"{spec.top.item} + {spec.bottom.item}", reason=reason)
        )
    unique = {(r.url, tuple(r.reasons)): r for r in rejected}  # pieces that share a search report each product once
    return FindProductsOutput(
        outfits=outfits, unfilled=unfilled, rejected=list(unique.values()), search_errors=sorted(set(errors))
    )
