"""find_products: typed input -> search -> verify every candidate -> typed output.

Only candidates whose verification says `is_match` can end up in an outfit. Everything rejected is
returned with the reasons, so a wrong result is visible rather than silently shown to the user.
"""

from concurrent.futures import ThreadPoolExecutor

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
from api.agent.verify import verify_product


def _reasons(product: Product) -> list[str]:
    report = product.verification
    assert report is not None
    return [
        f"{c.attribute}: asked '{c.requested}', found '{c.found}' ({c.status})"
        for c in report.checks
        if c.attribute in report.blocking
    ]


def _best_verified(
    hits: list[Product], spec: ItemSpec, used_urls: set[str], rejected: list[RejectedCandidate]
) -> Product | None:
    """Verify each hit; keep matches, record the rest. Best = highest match score, then price."""
    verified: list[Product] = []
    for hit in hits:
        reasons: list[str] = []
        checked = hit.model_copy(update={"verification": verify_product(hit, spec)})
        if not checked.verification.is_match:  # type: ignore[union-attr]
            reasons = _reasons(checked)
        elif hit.in_stock is False:
            reasons = ["availability: out of stock"]
        elif hit.url in used_urls:
            reasons = ["duplicate: already used in another outfit"]

        if reasons:
            rejected.append(
                RejectedCandidate(title=hit.title, retailer=hit.retailer, url=hit.url, reasons=reasons)
            )
        else:
            verified.append(checked)
    if not verified:
        return None
    # rank: confirmed attributes first, then higher match score, then higher price (under the cap)
    return max(
        verified,
        key=lambda p: (p.verification.confidence == "high", p.verification.score, p.price_inr),  # type: ignore[union-attr]
    )


def find_products_for_specs(inp: FindProductsInput, search: ProductSearch) -> FindProductsOutput:
    specs = inp.specs
    items = [s.top for s in specs] + [s.bottom for s in specs]
    errors: list[str] = []

    def safe_search(spec: ItemSpec) -> list[Product]:
        try:
            return search(spec)
        except SearchUnavailable as exc:  # one failed search must not crash the whole conversation
            errors.append(str(exc))
            return []

    with ThreadPoolExecutor(max_workers=8) as pool:  # all searches in parallel
        results = list(pool.map(safe_search, items))
    tops, bottoms = results[: len(specs)], results[len(specs) :]

    used_urls = set(inp.exclude_urls)
    outfits: list[Outfit] = []
    unfilled: list[UnfilledSpec] = []
    rejected: list[RejectedCandidate] = []
    for i, (spec, top_hits, bottom_hits) in enumerate(zip(specs, tops, bottoms, strict=True)):
        top = _best_verified(top_hits, spec.top, used_urls, rejected)
        bottom = _best_verified(bottom_hits, spec.bottom, used_urls, rejected)
        if top and bottom and top.price_inr + bottom.price_inr <= inp.budget_inr:
            used_urls |= {top.url, bottom.url}  # only reserve products that made it into an outfit
            low = "low" in (top.verification.confidence, bottom.verification.confidence)  # type: ignore[union-attr]
            outfits.append(
                Outfit(
                    top=top, bottom=bottom, rationale=spec.rationale,
                    total_inr=top.price_inr + bottom.price_inr,
                    confidence="low" if low else "high",
                )
            )
            continue
        missing = spec.top if not top else spec.bottom if not bottom else None
        if missing:
            reason = f"no verified match for '{missing.color} {missing.item}'"
        else:
            reason = "verified items exceed the total budget together"
        unfilled.append(
            UnfilledSpec(spec_index=i, item=f"{spec.top.item} + {spec.bottom.item}", reason=reason)
        )
    return FindProductsOutput(
        outfits=outfits, unfilled=unfilled, rejected=rejected, search_errors=sorted(set(errors))
    )
