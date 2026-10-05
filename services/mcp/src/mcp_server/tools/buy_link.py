"""get_buy_link: give back the store's own page for a product found by search_products. Costs NO search credit.

Search results already are the store's own product pages, so there is nothing more to look up: the search tool
remembers each product (server-side) and this tool returns its page after checking the host is an approved store.
Ids expire with the search cache, then the client must search again.
"""

from urllib.parse import urlparse, urlunparse

from fastmcp.exceptions import ToolError

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.schemas import BuyLinkResult, ProductResult, StoreOffer, ToolWarning
from mcp_server.tools.check_link import host_allowed


def _https(url: str, cfg: Settings) -> str:
    """Upgrade http:// to https://, but only for hosts we trust."""
    p = urlparse(url)
    if p.scheme == "http" and p.hostname and host_allowed(p.hostname, cfg.allowed_domains):
        return urlunparse(p._replace(scheme="https"))
    return url


async def run_buy_link(product_refs: TTLCache, cfg: Settings, product_id: str) -> BuyLinkResult:
    product: ProductResult | None = product_refs.get(product_id)
    if product is None:
        raise ToolError(
            "Unknown or expired product_id. Ids come from search_products and are valid for a "
            "few hours; run the search again."
        )
    url = _https(product.url, cfg)
    allowed = host_allowed(urlparse(url).hostname or "", cfg.allowed_domains)
    offer = StoreOffer(
        store=product.retailer, url=url, price_inr=product.price_inr, in_stock=product.in_stock,
        details=[], domain_allowed=allowed,
    )
    warnings = [] if allowed else [ToolWarning(code="NO_ALLOWED_STORE", message="the page is not on a store we show")]
    return BuyLinkResult(
        product_id=product_id, primary=offer if allowed else None, offers=[offer], from_cache=True, warnings=warnings
    )
