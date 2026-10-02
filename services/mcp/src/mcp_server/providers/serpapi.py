"""SerpAPI Google Shopping adapter. The only module that knows this provider's response shape.

Swapping providers later means writing another adapter with the same functions.
"""

import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from mcp_server.config import Settings
from mcp_server.net import UpstreamError, get_json
from mcp_server.schemas import ProductResult, StoreOffer


@dataclass
class DetailRef:
    """What we need to ask the provider 'which stores sell this product?' later (1 credit)."""

    url: str  # provider's detail URL (contains no key; we add the key when calling)
    title: str  # the provider requires a query text with the detail call
    retailer: str  # the store the product was listed under


@dataclass
class Parsed:
    product: ProductResult
    detail_ref: DetailRef | None


def _int(value) -> int | None:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _rupees(text: str | None) -> int | None:
    m = re.search(r"₹\s*([\d,]+)", text or "")
    return _int(m.group(1)) if m else None


def parse_shopping_results(data: dict) -> tuple[list[Parsed], int]:
    """Turn the raw response into ProductResults. Returns (parsed, number skipped)."""
    parsed, skipped = [], 0
    for raw in data.get("shopping_results", []):
        price = _int(raw.get("extracted_price"))
        if price is None or not raw.get("title"):
            skipped += 1
            continue
        link = raw.get("link")  # direct store link, when the API provides it
        product = ProductResult(
            product_id=str(raw.get("product_id") or raw.get("position")),
            title=raw["title"],
            retailer=raw.get("source") or "unknown",
            price_inr=price,
            mrp_inr=_rupees(raw.get("old_price")),  # e.g. "48% off₹1,999"
            url=link or raw.get("product_link") or "",
            url_kind="retailer" if link else "google_product_page",
            image_url=raw.get("thumbnail") or "",
            rating=float(raw["rating"]) if raw.get("rating") else None,
            reviews=_int(raw.get("reviews")),
            delivery=raw.get("delivery"),
        )
        if not product.url:
            skipped += 1
            continue
        detail_url = raw.get("serpapi_immersive_product_api")
        ref = DetailRef(detail_url, product.title, product.retailer) if detail_url else None
        parsed.append(Parsed(product, ref))
    return parsed, skipped


def parse_offers(data: dict) -> list[StoreOffer]:
    """Read the 'which stores sell this' response. domain_allowed is filled in by the tool."""
    offers = []
    for s in (data.get("product_results") or {}).get("stores", []):
        if not s.get("link"):
            continue
        details = s.get("details_and_offers") or []
        if isinstance(details, str):
            details = [details]
        text = " ".join(details).lower()
        in_stock = False if "out of stock" in text else True if "in stock" in text else None
        offers.append(
            StoreOffer(
                store=s.get("name") or "unknown", url=s["link"], price_inr=_rupees(s.get("price")),
                in_stock=in_stock, details=[str(d) for d in details], domain_allowed=False,
            )
        )
    return offers


class SerpApiShopping:
    def __init__(self, cfg: Settings, client: httpx.AsyncClient):
        self.cfg, self.client = cfg, client

    def _require_key(self) -> str:
        if not self.cfg.serpapi_api_key:
            raise UpstreamError("SERPAPI_API_KEY is not set on the tool server", retryable=False)
        return self.cfg.serpapi_api_key

    async def search(self, query: str) -> tuple[list[Parsed], int]:
        key = self._require_key()
        data = await get_json(
            self.client,
            self.cfg.serpapi_base_url,
            {"engine": "google_shopping", "q": query, "gl": "in", "hl": "en", "api_key": key},
        )
        if "error" in data:  # SerpAPI sometimes reports problems as a 200 with an 'error' field
            raise UpstreamError("search provider returned an error", retryable=False)
        return parse_shopping_results(data)

    async def offers(self, ref: DetailRef) -> list[StoreOffer]:
        key = self._require_key()
        # The detail URL already carries its own query string, so we append to it instead of
        # passing params= (which would replace it and silently turn this into a web search).
        url = f"{ref.url}&q={quote(ref.title)}&api_key={key}"
        data = await get_json(self.client, url, None)
        if "error" in data:
            raise UpstreamError("search provider returned an error", retryable=False)
        return parse_offers(data)
