"""OpenRouter web search with a model: FINDS candidate product pages in our approved stores.

OpenRouter gives a model a web search tool (`openrouter:web_search`, Exa engine by default) that can be restricted to a list of
domains. The model runs the search, READS the page excerpts it gets back, and answers with the product pages that fit what
the shopper asked for and the look they chose. Measured on real requests this finds what a ranked-results search does not: for
"olive oversized t-shirt" Tavily returned no olive tee at all, this returned eight, each from an approved store.

What it is NOT trusted for: price, image and stock. The model only reports what the excerpts say; the facts that decide
what the shopper sees are read from each store's own page afterwards (page_facts.py), exactly as for every other provider.
Every address is also checked here: only approved stores, only single-product pages. A model that names a store we do not
list, or invents a link, gets nothing through.

Limits found by testing: the domain filter is honoured up to about 70 domains (it is silently ignored at 100), so a search
covers at most `search_max_domains` of the chosen stores.
"""

import json
import logging
import re
from urllib.parse import urlparse

import httpx

from mcp_server.config import Settings
from mcp_server.net import UpstreamError
from mcp_server.providers.tavily import (
    Candidate,
    SearchOutcome,
    clean_title,
    looks_like_product_page,
    tidy_title,
)
from mcp_server.sellers import seller_for_host

log = logging.getLogger(__name__)

SYSTEM = (
    "You find real product pages for a man shopping for clothes in India. Use the web search tool. "
    "Return ONLY JSON: "
    '{"products":[{"title":"","url":"","store":"","colour_stated":"","fit_stated":"","price_inr":null}]} '
    "listing up to {n} single-product pages (never collection, category or search pages) that fit the request. "
    "Judge from the page content the search returns: prefer products whose own text states the colour and fit asked for. "
    "Use only what that content states; use null for anything it does not state. Never invent a product or a link."
)
_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_answer(text: str, *, limit: int = 20) -> SearchOutcome:
    """The model's answer as candidates. Pure function: no network. Anything that is not a single-product page of an
    approved store is skipped and counted."""
    match = _JSON.search(text or "")
    try:
        products = json.loads(match.group(0)).get("products") if match else None
    except ValueError:
        products = None
    if not isinstance(products, list):
        raise UpstreamError("the search model did not answer in the expected form", retryable=True)
    candidates: list[Candidate] = []
    seen: set[str] = set()
    skipped = 0
    for p in products:
        if not isinstance(p, dict):
            skipped += 1
            continue
        url = str(p.get("url") or "")
        parsed = urlparse(url)
        seller = seller_for_host(parsed.hostname or "") if parsed.scheme == "https" else None
        if seller is None or not p.get("title") or not looks_like_product_page(url):
            skipped += 1
            continue
        key = f"{(parsed.hostname or '').removeprefix('www.')}{parsed.path.rstrip('/')}".lower()
        if key in seen:
            continue
        seen.add(key)
        stated = "; ".join(
            f"{label}: {value}" for label, value in (("colour", p.get("colour_stated")), ("fit", p.get("fit_stated")))
            if value
        )
        candidates.append(
            Candidate(
                url=url, title=tidy_title(clean_title(str(p["title"]), seller.brand, seller.domain)),
                snippet=(f"The search says {stated}." if stated else "")[:400],
                relevance=None, retailer=seller.brand, domain=seller.domain,
            )
        )
        if len(candidates) >= limit:
            break
    return SearchOutcome(candidates, len(products), skipped, 1)


class OpenRouterSearch:
    credits_per_search = 1  # what the daily caps count (the real cost is in `cost_usd`)

    def __init__(self, cfg: Settings, client: httpx.AsyncClient):
        self.cfg, self.client = cfg, client

    def request_body(self, query: str, domains: list[str], context: str | None = None) -> dict:
        ask = f"Find: {query}."
        ask += " Only list pages on these stores (domains): " + ", ".join(domains[: self.cfg.search_max_domains]) + "."
        if context:
            ask += f" The shopper chose this look, so prefer pieces that suit it: {context}."
        return {
            "model": self.cfg.search_model,
            "messages": [
                {"role": "system", "content": SYSTEM.replace("{n}", str(self.cfg.search_results))},
                {"role": "user", "content": ask},
            ],
            "tools": [{
                "type": "openrouter:web_search",
                "parameters": {
                    "engine": self.cfg.search_engine,
                    "max_results": 10,
                    "max_uses": self.cfg.search_uses,
                    "max_total_results": 20,
                    "allowed_domains": domains[: self.cfg.search_max_domains],  # required by design: approved stores only
                },
            }],
        }

    async def search(self, query: str, domains: list[str], context: str | None = None) -> SearchOutcome:
        if not domains:
            raise UpstreamError("no stores to search", retryable=False)
        if not self.cfg.openrouter_api_key:
            raise UpstreamError("OPENROUTER_API_KEY is not set on the tool server", retryable=False)
        if len(domains) > self.cfg.search_max_domains:
            log.info("search covers %d of %d stores (the filter is honoured only up to that many)", self.cfg.search_max_domains, len(domains))
        headers = {"Authorization": f"Bearer {self.cfg.openrouter_api_key}"}
        url = f"{self.cfg.openrouter_base_url.rstrip('/')}/chat/completions"
        last = "unknown error"
        for attempt in range(2):  # a model call can fail transiently: one retry
            try:
                resp = await self.client.post(
                    url, json=self.request_body(query, domains, context), headers=headers,
                    timeout=httpx.Timeout(self.cfg.search_timeout_s, connect=8.0),
                )
            except httpx.TransportError as exc:
                last = type(exc).__name__
                continue
            if resp.status_code == 200:
                data = resp.json()
                try:
                    text = data["choices"][0]["message"].get("content") or ""
                except (KeyError, IndexError, AttributeError) as exc:
                    raise UpstreamError("the search model returned no answer", retryable=True) from exc
                outcome = parse_answer(text)
                cost = (data.get("usage") or {}).get("cost")
                outcome.cost_usd = float(cost) if isinstance(cost, int | float) else 0.0
                return outcome
            last = f"HTTP {resp.status_code}"
            if resp.status_code not in (429, 500, 502, 503, 504):
                raise UpstreamError(f"search provider rejected the request ({last})", retryable=False)
        raise UpstreamError(f"search provider unavailable ({last})", retryable=True)
