"""search_products: build a query, search, tidy the results. No MCP code in here, so it is easy to test.

Retrieval only. It does NOT decide whether a product really matches the request (colour, fit...):
the agent's verifier does that. Here we only drop things that can never be useful.
"""

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.providers.serpapi import Parsed
from mcp_server.schemas import SearchProductsResult, ToolWarning


def build_query(item: str, color: str, fit: str | None = None, fabric: str | None = None) -> str:
    """'men' is always included: this is a menswear app. Repeated words are dropped."""
    words: list[str] = []
    for part in ("men", color, fit or "", fabric or "", item):
        for w in part.lower().split():
            if w not in words:
                words.append(w)
    return " ".join(words)


def _retailer_allowed(name: str, allowed: tuple[str, ...]) -> bool:
    return any(a in name.lower() for a in allowed)


async def run_search(
    provider,
    cache: TTLCache,
    detail_refs: TTLCache,
    cfg: Settings,
    *,
    item: str,
    color: str,
    max_price_inr: int,
    fit: str | None = None,
    fabric: str | None = None,
    limit: int = 20,
) -> SearchProductsResult:
    query = build_query(item, color, fit, fabric)

    cached = cache.get(query)
    from_cache = cached is not None
    if cached is None:
        parsed, no_price = await provider.search(query)  # the only line that spends a credit
        cached = (parsed, no_price)
        cache.set(query, cached)
        for p in parsed:  # remember how to resolve each product's real store link later
            if p.detail_ref:
                detail_refs.set(p.product.product_id, p.detail_ref)
    parsed, no_price = cached

    warnings: list[ToolWarning] = []
    if no_price:
        warnings.append(ToolWarning(code="NO_PRICE", message="results without a usable price", count=no_price))

    kept: list[Parsed] = []
    wrong_store = over_cap = 0
    for p in parsed:
        if not _retailer_allowed(p.product.retailer, cfg.allowed_retailers):
            wrong_store += 1
        elif p.product.price_inr > max_price_inr:
            over_cap += 1
        else:
            kept.append(p)
    if wrong_store:
        warnings.append(ToolWarning(code="RETAILER_NOT_ALLOWED", message="results from stores we don't show", count=wrong_store))
    if over_cap:
        warnings.append(ToolWarning(code="PRICE_OVER_CAP", message="results above max_price_inr", count=over_cap))

    return SearchProductsResult(
        results=[p.product for p in kept[:limit]],
        query_used=query,
        from_cache=from_cache,
        warnings=warnings,
    )
