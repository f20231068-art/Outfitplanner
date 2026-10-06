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
from mcp_server.providers.openrouter_search import OpenRouterSearch
from mcp_server.providers.page_facts import read_page
from mcp_server.providers.tavily import TavilySearch
from mcp_server.schemas import BuyLinkResult, LinkCheckResult, SearchProductsResult
from mcp_server.sellers import GROUP_LABELS, StoreGroup
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

    def _spend(self, kind: str, credits: int) -> None:
        try:
            self._ledger.spend(caller_id(), credits)
        except LimitExceeded:
            LIMIT_HITS.labels("daily_credits").inc()
            raise
        CREDITS.labels(kind).inc(credits)

    async def search(self, query: str, domains: list[str], context: str | None = None):
        # an "advanced" Tavily search costs 2 credits; the provider knows its own price
        self._spend("search", getattr(self._inner, "credits_per_search", 1))
        return await self._inner.search(query, domains, context)


def build_server(
    cfg: Settings = settings, provider=None, http_client=None, resolver=None, page_reader=None
) -> FastMCP:
    """Factory so tests can inject a fake provider, page reader, HTTP client and DNS resolver (no network)."""
    # Fails closed: raises if the JWT public key is missing, so the server can never run open.
    mcp = FastMCP("stylist-tools", auth=build_verifier(cfg))
    http_client = http_client or make_client(cfg)
    ledger = CreditLedger(cfg.mcp_daily_credits_per_user, cfg.mcp_daily_credits_global)
    limiter = RateLimiter(cfg.mcp_rate_limit_per_min)
    default = OpenRouterSearch(cfg, http_client) if cfg.search_provider == "openrouter" else TavilySearch(cfg, http_client)
    provider = LimitedProvider(provider or default, ledger)
    search_cache = TTLCache(cfg.search_cache_ttl_s)
    product_refs = TTLCache(cfg.search_cache_ttl_s, max_items=5000)  # product_id -> the product (for get_buy_link)
    facts_cache = TTLCache(cfg.search_cache_ttl_s, max_items=5000)  # page url -> what the page states
    failed_cache = TTLCache(600, max_items=5000)  # page url -> True: could not be read, do not retry for 10 minutes
    read = page_reader or (lambda url: read_page(url, cfg, http_client, resolver or default_resolver))

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
        max_price_inr: Annotated[int, Field(description="Highest price for this single item, in rupees", gt=0)],
        fit: Annotated[str | None, Field(description="e.g. 'oversized', 'slim'")] = None,
        color: Annotated[
            str | None, Field(description="Colour to search for, e.g. 'olive green'. Optional: leave out to search every colour")
        ] = None,
        fabric: Annotated[str | None, Field(description="e.g. 'cotton', 'linen'")] = None,
        style: Annotated[
            str | None,
            Field(
                max_length=300,
                description="Optional: the look the shopper chose, e.g. 'Olive polo and beige chinos: relaxed smart casual'. "
                "The search model reads the pages for pieces that suit it",
            ),
        ] = None,
        keywords: Annotated[
            str | None,
            Field(
                max_length=120,
                description="Optional extra search words (a synonym or style word, 2-6 words), for a second try when "
                "the first search found too little, e.g. 'boxy drop shoulder'",
            ),
        ] = None,
        store_groups: Annotated[
            list[StoreGroup] | None,
            Field(
                description="Which groups of approved stores to search; leave out for all. One search covers "
                "every store in the chosen groups, so choose the groups that sell this garment. "
                + "; ".join(f"{k}: {v}" for k, v in GROUP_LABELS.items())
            ),
        ] = None,
        limit: Annotated[int, Field(description="Max products to return", ge=1, le=40)] = 20,
    ) -> SearchProductsResult:
        """Find men's clothing products in India for ONE garment (a top or a bottom, not a full outfit).

        Searches ONLY our approved menswear brands (D2C, heritage and ethnic specialists), restricted to the chosen
        store groups, with a single search that covers all of those stores, then reads each candidate store page for
        its price, image and stock. Returns candidate products (title, store, price, the store's own link, image,
        stock) exactly as the stores' pages state them; sold-out and unreadable pages are left out. Candidates are NOT checked against the request: a
        product may be the wrong colour or fit, so the caller must verify. Results may be empty.
        Each product has a product_id that stays valid for about 6 hours (pass it to get_buy_link).
        """
        with tracked("search_products"):
            throttle()
            try:
                result = await run_search(
                    provider, search_cache, product_refs, cfg,
                    item=item, color=color, max_price_inr=max_price_inr,
                    fit=fit, fabric=fabric, keywords=keywords, style=style, store_groups=store_groups, limit=limit,
                    page_reader=read, facts_cache=facts_cache, failed_cache=failed_cache,
                )
            except UpstreamError as exc:
                raise upstream_error(exc) from exc
            CACHE.labels("search_products", "hit" if result.from_cache else "miss").inc()
            return result

    @mcp.tool(annotations=READ_ONLY)
    async def get_buy_link(
        product_id: Annotated[str, Field(description="The product_id from a search_products result")],
    ) -> BuyLinkResult:
        """Get the store's own product page for one product from search_products. Costs no search credit.

        Call this when the user wants to buy. product_id is valid for about 6 hours after the search; after
        that it fails with an 'expired' error and the search must be repeated.
        """
        with tracked("get_buy_link"):
            throttle()
            try:
                result = await run_buy_link(product_refs, cfg, product_id)
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
