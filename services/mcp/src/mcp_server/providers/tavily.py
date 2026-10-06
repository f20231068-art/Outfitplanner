"""Tavily Search adapter: FINDS candidate product pages in our approved stores. The only module that knows Tavily's
request and response shape.

Why Tavily: it searches the web itself (not Google's shopping feed) and can be restricted to a list of domains, so
every result comes from one of our approved stores. One search = one credit (basic depth) and returns up to 20
pages, so ONE search covers a whole group of stores; we never spend a search per website.

What a Tavily result is: a web PAGE (title, url, a snippet, a relevance score). It is NOT a structured product, and
measured on real responses it cannot be trusted for price or image (the page text came back for about 1 result in 8,
and prices in snippets were often promo banners). So this module only does discovery. The facts (price, image, stock)
are read from each candidate page itself, see page_facts.py.
"""

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from mcp_server.config import Settings
from mcp_server.net import UpstreamError, post_json
from mcp_server.sellers import seller_for_host

# ---- page type ------------------------------------------------------------------------------------------------
_PRODUCT_HINTS = ("/products/", "/product/", "/p/", "/buy-", "/shop/", "/men-")
_NOT_A_PRODUCT = ("/blogs/", "/blog/", "/pages/", "/page/", "/search", "/cart", "/account", "/login", "/policies/",
                  "/category/", "/categories/", "/collections/", "/collection/", "/tag/", "/brand/", "/l/")
_NEEDS_A_SLUG = ("/men-",)  # "/men-t-shirts/" alone is a category; "/men-t-shirts/blue-polo/123" is a product


def looks_like_product_page(url: str) -> bool:
    """A single product page, as far as the address can tell. Category and search pages list many products and are
    skipped. (A product inside a collection URL, /collections/new/products/blue-polo, is still a product.)"""
    path = urlparse(url).path.lower()
    segments = [s for s in path.split("/") if s]
    if not segments:
        return False  # a home page
    if "/products/" in path or "/product/" in path or "/p/" in path or "/buy-" in path:
        return True
    if any(n in path + "/" for n in _NOT_A_PRODUCT):
        return False
    # a store's own address style (beyoung.in/blue-polo-t-shirt) passes: the page read decides if it is a product;
    # but "/men-t-shirts" with nothing after it is a category
    return not (path.startswith(_NEEDS_A_SLUG) and len(segments) < 2)


# ---- titles ---------------------------------------------------------------------------------------------------
_TITLE_SPLIT = re.compile(r"\s+[|–—-]\s+")


def clean_title(title: str, brand: str, domain: str) -> str:
    """Drop a trailing ' | Brand' or ' - brand.com' that a store appends to every page title."""
    parts = _TITLE_SPLIT.split(title.strip())
    stem = domain.split(".")[0].lower()
    while len(parts) > 1 and (brand.lower() in parts[-1].lower() or stem in parts[-1].lower().replace(" ", "")):
        parts.pop()
    return " - ".join(parts).strip() or title.strip()


_BUY_PREFIX = re.compile(r"^(?:buy|shop)\s+", re.IGNORECASE)
_STORE_TAIL = re.compile(r"\s+(?:online\b|at\s+[A-Z][\w&' .-]*$|in\s+india\b).*$", re.IGNORECASE)
_JUNK_NAME = re.compile(r"^(?:default title|title|untitled|product|[\d\W_]*)$", re.IGNORECASE)


def tidy_title(title: str) -> str:
    """A page title as a product name: 'Buy Blue Polo for Men Online in India' -> 'Blue Polo for Men'."""
    cleaned = _STORE_TAIL.sub("", _BUY_PREFIX.sub("", title.strip())).strip(" -|,")
    return cleaned or title.strip()


def good_product_name(name: str | None) -> bool:
    """False for the placeholders some stores put in their data ('Default Title', '30', a bare number)."""
    return bool(name) and len(name.strip()) >= 6 and not _JUNK_NAME.match(name.strip())


# ---- result -> candidate ----------------------------------------------------------------------------------------
@dataclass
class Candidate:
    """A page Tavily found. Nothing here is verified: the price and image come later, from the page itself."""

    url: str
    title: str
    snippet: str
    relevance: float | None
    retailer: str
    domain: str


@dataclass
class SearchOutcome:
    candidates: list[Candidate]  # product pages on approved stores, best first
    results_seen: int  # pages Tavily returned
    skipped_not_product: int  # not a single product page, or a store we do not list
    credits: int  # what this search cost
    cost_usd: float = 0.0  # the real money cost, when the provider reports it


def product_id_for(url: str) -> str:
    """A stable id from the address, so the same page is the same product in every search."""
    p = urlparse(url)
    canonical = f"{(p.hostname or '').removeprefix('www.')}{p.path.rstrip('/')}"
    return "t-" + hashlib.sha1(canonical.lower().encode()).hexdigest()[:12]


def parse_results(data: dict, *, credits: int) -> SearchOutcome:
    results = data.get("results") or []
    candidates: list[Candidate] = []
    skipped = 0
    seen: set[str] = set()
    for r in results:
        url = r.get("url") or ""
        seller = seller_for_host(urlparse(url).hostname or "")
        if seller is None or not r.get("title") or not looks_like_product_page(url):
            skipped += 1
            continue
        pid = product_id_for(url)
        if pid in seen:  # the same page twice (tracking parameters, with or without www)
            continue
        seen.add(pid)
        score = r.get("score")
        candidates.append(
            Candidate(
                url=url, title=tidy_title(clean_title(r["title"], seller.brand, seller.domain)),
                snippet=(r.get("content") or "")[:400],
                relevance=round(float(score), 3) if isinstance(score, int | float) else None,
                retailer=seller.brand, domain=seller.domain,
            )
        )
    return SearchOutcome(candidates, len(results), skipped, credits)


# ---- the call -------------------------------------------------------------------------------------------------
class TavilySearch:
    def __init__(self, cfg: Settings, client: httpx.AsyncClient):
        self.cfg, self.client = cfg, client

    @property
    def credits_per_search(self) -> int:
        return 2 if self.cfg.tavily_search_depth == "advanced" else 1

    def _require_key(self) -> str:
        if not self.cfg.tavily_api_key:
            raise UpstreamError("TAVILY_API_KEY is not set on the tool server", retryable=False)
        return self.cfg.tavily_api_key

    def request_body(self, query: str, domains: list[str]) -> dict:
        body: dict = {
            "query": query,
            "include_domains": domains,  # required by design: we only ever search approved stores
            "search_depth": self.cfg.tavily_search_depth,
            "max_results": self.cfg.tavily_max_results,
            "include_usage": True,
        }
        if self.cfg.tavily_country:
            body["country"] = self.cfg.tavily_country
        return body

    async def search(self, query: str, domains: list[str], context: str | None = None) -> SearchOutcome:
        if not domains:
            raise UpstreamError("no stores to search", retryable=False)
        key = self._require_key()
        data = await post_json(
            self.client, self.cfg.tavily_base_url, self.request_body(query, domains), {"Authorization": f"Bearer {key}"}
        )
        used = (data.get("usage") or {}).get("credits")
        return parse_results(data, credits=int(used) if isinstance(used, int | float) and used > 0 else self.credits_per_search)
