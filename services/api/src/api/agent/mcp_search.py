"""Product search through the MCP tool server (replaces mock_search).

The graph asks for products with `ProductSearch(spec) -> list[Product]`, a plain function. This
class is that function, but it calls the `search_products` tool on the MCP server over HTTP.
Every HTTP request carries a fresh signed token (see api/mcp_auth.py) naming the end user.
"""

import asyncio
import logging
from collections.abc import Callable

from fastmcp import Client
from fastmcp.exceptions import ToolError

from api.agent.products import SearchUnavailable
from api.agent.schemas import ItemSpec, Product
from api.config import Settings, settings
from api.mcp_auth import ServiceTokenAuth

log = logging.getLogger(__name__)
ATTEMPTS = 2  # a transient connection failure gets one retry; deliberate refusals never do


def product_from_tool_result(item: dict) -> Product:
    """One entry of the tool's `results` list, as a Product. Nothing is invented: the tool already
    gave us these fields, and the verifier checks them against the request afterwards."""
    return Product(
        product_id=item["product_id"],
        title=item["title"],
        retailer=item["retailer"],
        price_inr=item["price_inr"],
        mrp_inr=item.get("mrp_inr"),
        url=item["url"],
        url_kind=item.get("url_kind"),
        image_url=item.get("image_url") or "",
        description=item.get("description") or "",
        details=item.get("details") or "",
        relevance=item.get("relevance"),
        in_stock=item.get("in_stock"),
        attributes=item.get("attributes") or {},
        rating=item.get("rating"),
        reviews=item.get("reviews"),
        delivery=item.get("delivery"),
        extraction=item.get("extraction", "store_page"),
    )


class McpProductSearch:
    """Callable `ProductSearch`. One instance per user request, so the token names that user."""

    def __init__(
        self,
        user_id: str,
        cfg: Settings = settings,
        client_factory: Callable[[], Client] | None = None,
        limit: int = 20,
    ):
        self.user_id, self.cfg, self.limit = user_id, cfg, limit
        # tests pass a factory that points at an in-process server instead of the network
        self._client_factory = client_factory or (
            lambda: Client(cfg.mcp_url, auth=ServiceTokenAuth(user_id, cfg), timeout=30)
        )

    async def _search(self, spec: ItemSpec) -> list[Product]:
        args = {
            "item": spec.item,
            "max_price_inr": spec.max_price_inr,
            "limit": self.limit,
            **({"color": spec.color} if spec.color else {}),
            **({"store_groups": spec.store_groups} if spec.store_groups else {}),  # one search covers these stores
            **({"fit": spec.fit} if spec.fit else {}),
            **({"fabric": spec.fabric} if spec.fabric else {}),
            **({"keywords": spec.keywords} if spec.keywords else {}),
        }
        for attempt in range(ATTEMPTS):
            try:
                async with self._client_factory() as client:
                    result = await client.call_tool("search_products", args)
                break
            except ToolError as exc:  # refused on purpose (limits, provider error): its message is user-safe
                raise SearchUnavailable(str(exc)) from exc
            except Exception as exc:  # network blip, server restarting...
                log.warning("MCP search failed (try %d/%d): %s: %s", attempt + 1, ATTEMPTS, type(exc).__name__, exc)
                if attempt == ATTEMPTS - 1:  # never leak technical detail to the shopper
                    raise SearchUnavailable("The shopping search is not reachable right now.") from exc
                await asyncio.sleep(0.5)
        data = result.structured_content or {}
        return [product_from_tool_result(item) for item in data.get("results", [])]

    def __call__(self, spec: ItemSpec) -> list[Product]:
        # find_products runs searches in worker threads, so each call gets its own event loop
        return asyncio.run(self._search(spec))
