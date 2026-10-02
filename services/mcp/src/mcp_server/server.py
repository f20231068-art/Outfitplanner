"""The MCP server: thin wrappers that expose plain Python functions as MCP tools.

Run:  uv run python -m mcp_server.server        (listens on http://127.0.0.1:8001/mcp)

Adding a tool = write the logic in tools/<name>.py, wrap it here with @mcp.tool (name from the
function, description from the docstring, input/output schemas from the type hints), restart.
"""

import hmac
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import Field
from starlette.responses import JSONResponse, Response

from mcp_server.auth import build_verifier
from mcp_server.cache import TTLCache
from mcp_server.config import Settings, settings
from mcp_server.limits import CreditLedger, LimitExceeded, RateLimiter
from mcp_server.metrics import CACHE, CREDITS, LIMIT_HITS, tracked
from mcp_server.net import UpstreamError, make_client
from mcp_server.providers.serpapi import SerpApiShopping
from mcp_server.schemas import BuyLinkResult, LinkCheckResult, SearchProductsResult
from mcp_server.tools.buy_link import run_buy_link
from mcp_server.tools.check_link import default_resolver, run_check
from mcp_server.tools.search_products import run_search

# Tells clients these tools never change anything (they only read), so they are safe to retry.
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}


def http_guard(cfg: Settings) -> dict:
    """Always check the Host/Origin headers. Stops a web page in your browser from reaching a
    local server by pointing a hostname at 127.0.0.1 (DNS rebinding)."""
    return {"host_origin_protection": True, "allowed_hosts": cfg.allowed_hosts_list}


LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def assert_safe_bind(cfg: Settings) -> None:
    """Listening on anything but this machine is only allowed when the server also knows which
    host names it may be reached by, so it can never be started wide open by accident."""
    if cfg.mcp_host not in LOOPBACK_HOSTS and not cfg.allowed_hosts_list:
        raise RuntimeError(
            f"MCP_HOST={cfg.mcp_host!r} would expose the server beyond this machine, but MCP_ALLOWED_HOSTS "
            "is empty. Set it to the private name other services use to reach this server."
        )


def caller_id() -> str:
    """Who is calling: the user id inside the verified token (anonymous only in in-process tests)."""
    token = get_access_token()
    return token.subject if token is not None and token.subject else "anonymous"


class LimitedProvider:
    """Wraps the search provider so every PAID call is counted against the daily credit caps.
    Cache hits never reach it, so they cost nothing and are never counted."""

    def __init__(self, inner, ledger: CreditLedger):
        self._inner, self._ledger = inner, ledger

    def _spend(self, kind: str) -> None:
        try:
            self._ledger.spend(caller_id(), 1)
        except LimitExceeded:
            LIMIT_HITS.labels("daily_credits").inc()
            raise
        CREDITS.labels(kind).inc()

    async def search(self, query: str):
        self._spend("search")
        return await self._inner.search(query)

    async def offers(self, ref):
        self._spend("buy_link")
        return await self._inner.offers(ref)


def build_server(
    cfg: Settings = settings, provider=None, http_client=None, resolver=None
) -> FastMCP:
    """Factory so tests can inject a fake provider, HTTP client and DNS resolver (no network)."""
    # Fails closed: raises if the JWT public key is missing, so the server can never run open.
    mcp = FastMCP("stylist-tools", auth=build_verifier(cfg))
    http_client = http_client or make_client(cfg)
    ledger = CreditLedger(cfg.mcp_daily_credits_per_user, cfg.mcp_daily_credits_global)
    limiter = RateLimiter(cfg.mcp_rate_limit_per_min)
    provider = LimitedProvider(provider or SerpApiShopping(cfg, http_client), ledger)
    search_cache = TTLCache(cfg.search_cache_ttl_s)
    detail_refs = TTLCache(cfg.search_cache_ttl_s, max_items=5000)  # product_id -> how to look it up
    link_cache = TTLCache(cfg.search_cache_ttl_s)

    def upstream_error(exc: UpstreamError) -> ToolError:
        return ToolError(f"{exc}." + (" You can retry." if exc.retryable else ""))

    def throttle() -> None:
        """Called first by every tool: refuses a user who is calling too fast."""
        try:
            limiter.check(caller_id())
        except LimitExceeded as exc:
            LIMIT_HITS.labels("rate").inc()
            raise ToolError(str(exc)) from exc

    @mcp.custom_route("/metrics", methods=["GET"])
    async def metrics(request):
        """Prometheus scrapes this over the private network. Off unless METRICS_TOKEN is set."""
        if not cfg.metrics_token:
            return JSONResponse({"detail": "Not found."}, status_code=404)
        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(sent.encode(), cfg.metrics_token.encode()):
            return JSONResponse({"detail": "Unauthorized."}, status_code=401)
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):
        """For the host's liveness check. No login needed, and it reveals nothing but 'ok'."""
        return JSONResponse({"status": "ok"})

    @mcp.tool(annotations=READ_ONLY)
    def ping() -> str:
        """Health check. Returns 'pong'."""
        with tracked("ping"):
            throttle()
            return "pong"

    @mcp.tool(annotations=READ_ONLY)
    async def search_products(
        item: Annotated[str, Field(description="Garment to find, e.g. 't-shirt', 'cargo pants', 'chinos'")],
        color: Annotated[str, Field(description="Colour wanted, e.g. 'olive green'. Always part of the search")],
        max_price_inr: Annotated[int, Field(description="Highest price for this single item, in rupees", gt=0)],
        fit: Annotated[str | None, Field(description="e.g. 'oversized', 'slim'")] = None,
        fabric: Annotated[str | None, Field(description="e.g. 'cotton', 'linen'")] = None,
        limit: Annotated[int, Field(description="Max products to return", ge=1, le=40)] = 20,
    ) -> SearchProductsResult:
        """Find men's clothing products in India for ONE garment (a top or a bottom, not a full outfit).

        Returns candidate products (title, store, price, link, image) from Indian retailers such as
        Myntra, Amazon.in, Flipkart and AJIO. Candidates are NOT checked against the request: a
        product may be the wrong colour or fit, so the caller must verify. Results may be empty.
        Each product has a product_id that stays valid for about 6 hours (pass it to get_buy_link).
        """
        with tracked("search_products"):
            throttle()
            try:
                result = await run_search(
                    provider, search_cache, detail_refs, cfg,
                    item=item, color=color, max_price_inr=max_price_inr,
                    fit=fit, fabric=fabric, limit=limit,
                )
            except UpstreamError as exc:
                raise upstream_error(exc) from exc
            CACHE.labels("search_products", "hit" if result.from_cache else "miss").inc()
            return result

    @mcp.tool(annotations=READ_ONLY)
    async def get_buy_link(
        product_id: Annotated[str, Field(description="The product_id from a search_products result")],
    ) -> BuyLinkResult:
        """Get the store's own product page (and stock) for one product from search_products.

        Search results only link to a Google Shopping page; call this when the user wants to buy.
        It costs one search credit, so call it only for products the user actually picks.
        product_id is valid for about 6 hours after the search; after that it fails with an
        'expired' error and the search must be repeated.
        """
        with tracked("get_buy_link"):
            throttle()
            try:
                result = await run_buy_link(provider, detail_refs, link_cache, cfg, product_id)
            except UpstreamError as exc:
                raise upstream_error(exc) from exc
            CACHE.labels("get_buy_link", "hit" if result.from_cache else "miss").inc()
            return result

    @mcp.tool(annotations=READ_ONLY)
    async def check_link(
        url: Annotated[str, Field(description="https link to a product page on an allowed store")],
    ) -> LinkCheckResult:
        """Check whether a store link is still live.

        verdict is 'live', 'dead' (page gone) or 'unverified' (we could not tell, e.g. the store
        blocks automated checks, which does NOT mean the link is broken). Only https links on
        allow-listed stores are checked; anything else is refused.
        """
        with tracked("check_link"):
            throttle()
            return await run_check(url, cfg, http_client, resolver or default_resolver)

    return mcp


if __name__ == "__main__":
    assert_safe_bind(settings)
    build_server().run(
        transport="http", host=settings.mcp_host, port=settings.mcp_port, **http_guard(settings)
    )
