"""Read what a store's OWN product page says about itself: price, image, stock, colour.

Why: Tavily finds the right pages but its results carry no reliable price or image (measured on real responses: the
page text came back for about 1 result in 8, and when a price was in the snippet it was often a promo banner such as
"FLAT 100 OFF"). The stores publish the facts themselves in the page, in a standard machine-readable form
(schema.org `Product` JSON-LD, plus Open Graph meta tags). Reading those is free, exact, and also gives stock.

It is a page FETCH, so it is held to the same safety rules as check_link (https only, approved stores only, public
addresses only, connect to the address that was checked, every redirect re-checked) plus a hard size and time limit.
No model is involved: a page that does not state a fact simply yields None.
"""

import asyncio
import html as html_lib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from mcp_server.config import Settings
from mcp_server.tools.check_link import MAX_REDIRECTS, Resolver, _pin, _vet, default_resolver

# A browser-compatible agent string: several approved stores answer 403 to anything else.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
MAX_PAGE_BYTES = 2_500_000  # product pages with inline data run to ~1.2 MB; never read more than this
READ_TIMEOUT_S = 9.0

_LD_JSON = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_ATTR = re.compile(r'([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
_IN_STOCK = ("instock", "limitedavailability", "onlineonly", "instoreonly")
_OUT_OF_STOCK = ("outofstock", "soldout", "discontinued")


@dataclass
class PageFacts:
    name: str | None = None
    price_inr: int | None = None
    image_url: str = ""
    in_stock: bool | None = None  # None = the page did not say
    color: str | None = None
    material: str | None = None
    details: str = ""  # the page's own description of the product (what a shopper reads), trimmed
    sources: list[str] = field(default_factory=list)  # which parts of the page gave facts: json_ld, open_graph


def _types(node: dict) -> list[str]:
    t = node.get("@type")
    return [t] if isinstance(t, str) else [x for x in t if isinstance(x, str)] if isinstance(t, list) else []


def _find_products(node):
    if isinstance(node, list):
        for n in node:
            yield from _find_products(n)
    elif isinstance(node, dict):
        if "Product" in _types(node):
            yield node
        for v in node.values():
            if isinstance(v, dict | list):
                yield from _find_products(v)


def _number(value) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _first_text(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("name") or value.get("url")
    return str(value).strip() if value not in (None, "") else None


def _offers(product: dict) -> list[dict]:
    raw = product.get("offers")
    items = raw if isinstance(raw, list) else [raw] if raw else []
    flat: list[dict] = []
    for o in items:
        if isinstance(o, dict):
            nested = o.get("offers")  # an AggregateOffer may hold the individual offers
            flat += [x for x in (nested if isinstance(nested, list) else []) if isinstance(x, dict)] or [o]
    return flat


def _stock_of(offer: dict) -> bool | None:
    a = str(offer.get("availability") or "").rsplit("/", 1)[-1].lower().replace("_", "")
    if a in _IN_STOCK:
        return True
    if a in _OUT_OF_STOCK:
        return False
    return None  # PreOrder, BackOrder, or nothing stated


def _from_product(product: dict, base_url: str, facts: PageFacts) -> None:
    offers = _offers(product)
    states = [_stock_of(o) for o in offers]
    # variants: sold out only if EVERY variant says so; the price is the cheapest one that can be bought
    if any(s is True for s in states):
        facts.in_stock = True
    elif states and all(s is False for s in states):
        facts.in_stock = False
    buyable = [o for o, s in zip(offers, states, strict=True) if s is not False] or offers
    prices = []
    for o in buyable:
        currency = str(o.get("priceCurrency") or (o.get("priceSpecification") or {}).get("priceCurrency") or "INR").upper()
        n = _number(o.get("price") if o.get("price") not in (None, "") else (o.get("priceSpecification") or {}).get("price", o.get("lowPrice")))
        if n and currency == "INR":
            prices.append(n)
    if prices:
        facts.price_inr = round(min(prices))
    facts.image_url = _image_url(_first_text(product.get("image")), base_url)
    facts.name = _first_text(product.get("name")) or facts.name
    facts.color = _first_text(product.get("color")) or facts.color
    facts.material = _first_text(product.get("material")) or facts.material
    facts.details = _details(_first_text(product.get("description"))) or facts.details
    facts.sources.append("json_ld")


MAX_DETAILS_CHARS = 500
_TAGS = re.compile(r"<[^>]+>")


def _details(raw: str | None) -> str:
    """A page description as plain text on one line: tags removed, whitespace collapsed, cut at a word."""
    if not raw:
        return ""
    text = " ".join(html_lib.unescape(_TAGS.sub(" ", str(raw))).split())
    if len(text) <= MAX_DETAILS_CHARS:
        return text
    return text[:MAX_DETAILS_CHARS].rsplit(" ", 1)[0] + "..."


_NOT_A_PRODUCT_IMAGE = ("logo", "favicon", "icon", "sprite", "placeholder", "default-image", "banner")


def _image_url(raw: str | None, base_url: str) -> str:
    """An absolute https image address, or '' if it is missing or looks like a logo (a page's og:image is often the
    store's logo, which is not a product photo)."""
    if not raw:
        return ""
    url = urljoin(base_url, raw.strip())
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]  # the page is served over https; a plain-http image would be blocked
    return "" if any(bad in url.lower() for bad in _NOT_A_PRODUCT_IMAGE) else url


def _meta_tags(html: str) -> dict[str, str]:
    tags: dict[str, str] = {}
    for tag in _META.findall(html):
        attrs = {m.group(1).lower(): (m.group(2) if m.group(2) is not None else m.group(3)) for m in _ATTR.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        if key and "content" in attrs:
            tags.setdefault(key, attrs["content"])
    return tags


def parse_facts(html: str, base_url: str) -> PageFacts:
    """What a product page's own data says. Pure function: no network, easy to test."""
    facts = PageFacts()
    for blob in _LD_JSON.findall(html):
        try:
            data = json.loads(blob.strip())
        except ValueError:
            continue
        for product in _find_products(data):
            _from_product(product, base_url, facts)
            break  # the first Product on the page is the page's product
        if "json_ld" in facts.sources:
            break
    meta = _meta_tags(html)
    if not facts.image_url and _image_url(meta.get("og:image"), base_url):
        facts.image_url = _image_url(meta["og:image"], base_url)
        facts.sources.append("open_graph")
    if facts.price_inr is None:
        n = _number(meta.get("product:price:amount") or meta.get("og:price:amount"))
        currency = (meta.get("product:price:currency") or meta.get("og:price:currency") or "INR").upper()
        if n and currency == "INR":
            facts.price_inr = round(n)
            facts.sources.append("open_graph")
    if not facts.details:
        facts.details = _details(meta.get("og:description") or meta.get("description"))
    if facts.in_stock is None and meta.get("product:availability"):
        facts.in_stock = _stock_of({"availability": meta["product:availability"].replace(" ", "")})
    return facts


async def read_page(
    url: str, cfg: Settings, client: httpx.AsyncClient, resolver: Resolver = default_resolver
) -> PageFacts | None:
    """Fetch a product page and read its facts. None means the page could not be read (not allowed, blocked, down,
    too slow): the caller treats that as 'no verified price', never as a guess."""
    refusal, ip = await _vet(url, cfg, resolver)
    if refusal or ip is None:
        return None
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        host = urlparse(current).hostname or ""
        try:
            async with asyncio.timeout(READ_TIMEOUT_S):
                async with client.stream(
                    "GET", _pin(current, ip),
                    headers={"User-Agent": USER_AGENT, "Host": host, "Accept": "text/html,application/xhtml+xml",
                             "Accept-Language": "en-IN,en;q=0.9"},
                    extensions={"sni_hostname": host}, follow_redirects=False,
                ) as resp:
                    status, location = resp.status_code, resp.headers.get("location")
                    if status == 200:
                        chunks, size = [], 0
                        async for chunk in resp.aiter_bytes():
                            chunks.append(chunk)
                            size += len(chunk)
                            if size >= MAX_PAGE_BYTES:
                                break
                        body = b"".join(chunks).decode("utf-8", errors="ignore")
        except (httpx.HTTPError, TimeoutError):
            return None
        if 300 <= status < 400 and location:
            if hop == MAX_REDIRECTS:
                return None
            current = urljoin(current, location)
            refusal, next_ip = await _vet(current, cfg, resolver)  # every hop passes the same checks
            if refusal or next_ip is None:
                return None
            ip = next_ip
            continue
        return parse_facts(body, current) if status == 200 else None
    return None
