"""search_products: find candidate pages with ONE Tavily search, then read each page's own facts.

No MCP code in here, so it is easy to test.

  1. DISCOVER: one search covers every store in the chosen groups (Tavily is restricted to those domains), so a search
     costs one credit whether it covers 5 stores or 60. Cached for a few hours by (query, groups).
  2. READ: for the best candidates, read the store's own page for its price, image and stock (providers/page_facts.py).
     Free, exact, and cached per page. A page that cannot be read, or states no price, or is sold out, is not returned.

Retrieval only. It does NOT decide whether a product really matches the request (colour, fit...): the agent's
verifier does that. Here we only drop things that can never be useful.
"""

import asyncio
import html
from collections.abc import Awaitable, Callable

from mcp_server.cache import TTLCache
from mcp_server.config import Settings
from mcp_server.providers.page_facts import PageFacts
from mcp_server.providers.tavily import (
    Candidate,
    SearchOutcome,
    good_product_name,
    product_id_for,
    tidy_title,
)
from mcp_server.schemas import ProductResult, SearchProductsResult, ToolWarning
from mcp_server.sellers import GROUPS, domains_for

PageReader = Callable[[str], Awaitable[PageFacts | None]]


MAX_KEYWORDS_CHARS = 60


def clean_keywords(raw: str | None) -> str:
    """Extra search words from the caller: letters, digits, spaces and hyphens only, and short. The text goes into a
    search query, so nothing else is let through."""
    kept = "".join(ch if (ch.isalnum() or ch in " -") else " " for ch in (raw or ""))
    return " ".join(kept.split())[:MAX_KEYWORDS_CHARS].strip()


def search_chunks(groups: list[str], cfg: Settings) -> list[list[str]]:
    """The store groups split into searches. The model search keeps to the stores only while the list is short, so groups are
    packed, in order, into chunks of at most `search_chunk_domains` stores. Other providers search everything at once."""
    if cfg.search_provider != "openrouter":
        return [list(groups)]
    chunks: list[list[str]] = []
    size = 0
    for g in groups:
        n = len([d for d in domains_for([g]) if d in cfg.allowed_domains])
        if chunks and size + n <= cfg.search_chunk_domains:
            chunks[-1].append(g)
            size += n
        else:
            chunks.append([g])
            size = n
    return chunks


def merge_outcomes(outcomes: list[SearchOutcome]) -> SearchOutcome:
    """The chunks' candidates as one list: taken in turn from each chunk (so reading the first pages covers every chunk), each
    page once."""
    seen: set[str] = set()
    merged: list[Candidate] = []
    longest = max((len(o.candidates) for o in outcomes), default=0)
    for i in range(longest):
        for o in outcomes:
            if i < len(o.candidates):
                c = o.candidates[i]
                pid = product_id_for(c.url)
                if pid not in seen:
                    seen.add(pid)
                    merged.append(c)
    return SearchOutcome(
        merged, sum(o.results_seen for o in outcomes), sum(o.skipped_not_product for o in outcomes),
        sum(o.credits for o in outcomes), sum(o.cost_usd for o in outcomes),
    )


def build_query(
    item: str, color: str | None = None, fit: str | None = None, fabric: str | None = None, keywords: str | None = None
) -> str:
    """'blue slim polo t-shirt for men'. Repeated words are dropped; 'men' is always there (menswear app).
    `keywords` are extra words (a synonym, a style word) for a second try when the first search found too little."""
    words: list[str] = []
    for part in (color or "", fit or "", fabric or "", item, clean_keywords(keywords)):
        for w in part.lower().split():
            if w not in words:
                words.append(w)
    text = " ".join(words)
    return text if "men" in words or "mens" in words else f"{text} for men"


def product_from(candidate: Candidate, facts: PageFacts) -> ProductResult:
    """A product whose every fact the store's own page stated. The title prefers the page's own product name."""
    attributes = {k: v for k, v in (("color", facts.color), ("fabric", facts.material)) if v}
    return ProductResult(
        product_id=product_id_for(candidate.url),
        title=html.unescape(facts.name if good_product_name(facts.name) else tidy_title(candidate.title)),
        retailer=candidate.retailer,
        price_inr=facts.price_inr or 0,
        url=candidate.url,
        image_url=facts.image_url,
        description=candidate.snippet[:300],
        details=facts.details,
        relevance=candidate.relevance,
        in_stock=facts.in_stock,
        attributes=attributes,
    )


async def _read_all(
    candidates: list[Candidate], read: PageReader, facts_cache: TTLCache, failed_cache: TTLCache, concurrency: int
) -> list[PageFacts | None]:
    """Each candidate's facts. A page read once is remembered; so is a failure (for a shorter time), so a store that
    blocks us is not hammered."""
    gate = asyncio.Semaphore(concurrency)

    async def one(c: Candidate) -> PageFacts | None:
        cached = facts_cache.get(c.url)
        if cached is not None:
            return cached
        if failed_cache.get(c.url):
            return None
        async with gate:
            facts = await read(c.url)
        if facts is None:
            failed_cache.set(c.url, True)
        else:
            facts_cache.set(c.url, facts)
        return facts

    return list(await asyncio.gather(*[one(c) for c in candidates]))


async def run_search(
    provider,
    cache: TTLCache,
    product_refs: TTLCache,
    cfg: Settings,
    *,
    item: str,
    color: str | None,
    max_price_inr: int,
    fit: str | None = None,
    fabric: str | None = None,
    keywords: str | None = None,
    style: str | None = None,
    store_groups: list[str] | None = None,
    limit: int = 20,
    page_reader: PageReader,
    facts_cache: TTLCache,
    failed_cache: TTLCache,
) -> SearchProductsResult:
    chosen = set(store_groups or GROUPS)
    groups = [g for g in GROUPS if g in chosen]  # canonical order, so the cache key does not depend on input order
    domains = [d for d in domains_for(groups) if d in cfg.allowed_domains]
    query = build_query(item, color, fit, fabric, keywords)
    context = " ".join((style or "").split())[:300] or None  # the look the shopper chose: the search model reads for it

    # One search per CHUNK of stores (the model search keeps to the stores only while the list is short), all at once.
    chunks = search_chunks(groups, cfg)

    async def search_chunk(chunk_groups: list[str]) -> tuple[SearchOutcome, bool]:
        chunk_domains = [d for g in chunk_groups for d in domains_for([g]) if d in cfg.allowed_domains]
        key = f"{query}|{','.join(chunk_groups)}|{context or ''}"
        cached = cache.get(key)
        if cached is not None:
            return cached, True
        found = await provider.search(query, chunk_domains, context)  # the only line that spends a credit
        if found.candidates:  # an empty answer is never remembered: it would turn one blank reply into hours of blank replies
            cache.set(key, found)
        return found, False

    answers = await asyncio.gather(*[search_chunk(c) for c in chunks], return_exceptions=True)
    done = [a for a in answers if not isinstance(a, BaseException)]
    if not done:  # every chunk failed: report the first failure
        raise next(a for a in answers if isinstance(a, BaseException))
    outcome = merge_outcomes([o for o, _ in done])
    from_cache = all(c for _, c in done)

    # Best candidates first (Tavily orders by relevance), a batch at a time, until there are enough usable products
    candidates = outcome.candidates[: cfg.page_reads_per_search]
    unreadable = no_price = sold_out = pages_read = 0
    products: list[ProductResult] = []
    for start in range(0, len(candidates), cfg.page_read_batch):
        batch = candidates[start : start + cfg.page_read_batch]
        for candidate, facts in zip(batch, await _read_all(batch, page_reader, facts_cache, failed_cache, cfg.page_read_batch), strict=True):
            if facts is None:
                unreadable += 1
            elif not facts.price_inr:
                no_price += 1
            elif facts.in_stock is False:
                sold_out += 1
            else:
                products.append(product_from(candidate, facts))
        pages_read += len(batch)
        if sum(p.price_inr <= max_price_inr for p in products) >= cfg.enough_products:
            break
    for p in products:  # remember each product so get_buy_link can return its page (no credit needed)
        product_refs.set(p.product_id, p)

    kept = [p for p in products if p.price_inr <= max_price_inr]
    skipped = [
        ("NOT_A_PRODUCT_PAGE", "results that were not a single product page, or not an approved store", outcome.skipped_not_product),
        ("PAGE_UNREADABLE", "store pages that could not be read (blocked or down)", unreadable),
        ("NO_PRICE", "store pages that state no price", no_price),
        ("OUT_OF_STOCK", "store pages that say the item is sold out", sold_out),
        ("PRICE_OVER_CAP", "results above max_price_inr", len(products) - len(kept)),
    ]
    return SearchProductsResult(
        results=kept[:limit],
        query_used=query,
        store_groups=groups,
        stores_searched=len(domains),
        pages_read=pages_read,
        credits_spent=0 if from_cache else outcome.credits,
        search_cost_usd=0.0 if from_cache else outcome.cost_usd,
        from_cache=from_cache,
        warnings=[ToolWarning(code=c, message=m, count=n) for c, m, n in skipped if n],
    )
