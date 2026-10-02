"""get_buy_link: turn a search result into the store's own page. Costs one search credit.

The search tool remembers (server-side) how to look each product up, so the client only needs to
pass the opaque product_id. Ids expire with the search cache, then the client must search again.
"""

from urllib.parse import urlparse, urlunparse

from fastmcp.exceptions import ToolError

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.providers.serpapi import DetailRef
from mcp_server.schemas import BuyLinkResult, StoreOffer, ToolWarning
from mcp_server.tools.check_link import host_allowed


def _https(url: str, cfg: Settings) -> str:
    """Stores often return http:// links. Upgrade to https, but only for hosts we trust."""
    p = urlparse(url)
    if p.scheme == "http" and p.hostname and host_allowed(p.hostname, cfg.allowed_domains):
        return urlunparse(p._replace(scheme="https"))
    return url


def _same_store(offer_store: str, listed_as: str) -> bool:
    a, b = offer_store.lower(), listed_as.lower()
    return a in b or b in a  # "Myntra" vs "Myntra - BeYoung"


async def run_buy_link(
    provider, detail_refs: TTLCache, link_cache: TTLCache, cfg: Settings, product_id: str
) -> BuyLinkResult:
    cached = link_cache.get(product_id)
    if cached is not None:
        return cached.model_copy(update={"from_cache": True})

    ref: DetailRef | None = detail_refs.get(product_id)
    if ref is None:
        raise ToolError(
            "Unknown or expired product_id. Ids come from search_products and are valid for a "
            "few hours; run the search again."
        )

    offers: list[StoreOffer] = []
    for o in await provider.offers(ref):  # the only line that spends a credit
        url = _https(o.url, cfg)
        host = urlparse(url).hostname or ""
        offers.append(o.model_copy(update={"url": url, "domain_allowed": host_allowed(host, cfg.allowed_domains)}))

    usable = [o for o in offers if o.domain_allowed]
    primary = next((o for o in usable if _same_store(o.store, ref.retailer)), usable[0] if usable else None)
    warnings = []
    if offers and not usable:
        warnings.append(ToolWarning(code="NO_ALLOWED_STORE", message="no offer is from a store we show"))
    if not offers:
        warnings.append(ToolWarning(code="NO_OFFERS", message="the provider listed no stores for this product"))

    result = BuyLinkResult(product_id=product_id, primary=primary, offers=offers, from_cache=False, warnings=warnings)
    link_cache.set(product_id, result)
    return result
