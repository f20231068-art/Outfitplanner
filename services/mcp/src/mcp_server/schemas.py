"""The data contract of the tools. FastMCP turns these into the JSON Schemas clients see."""

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


class ProductResult(BaseModel):
    """One candidate product, exactly as the shopping data reports it (nothing invented)."""

    product_id: str = Field(description="Opaque id; pass to get_buy_link to get the store's own URL")
    title: str = Field(description="The page's own title, with the store's name suffix removed")
    retailer: str = Field(description="Store name from the approved seller list, e.g. 'Snitch'")
    price_inr: int = Field(description="Selling price in whole rupees, as the store's own page states it (never guessed)")
    mrp_inr: int | None = Field(None, description="List price before discount, if the page shows one")
    url: str = Field(description="The store's own product page")
    url_kind: Literal["retailer"] = Field("retailer", description="Always the store's own page")
    image_url: str = Field(description="The product image the store's page names; empty if it names none")
    description: str = Field("", description="The start of the search snippet for the page: extra evidence for checks")
    details: str = Field("", description="The product page's own description (up to ~500 characters), for a reader that judges whether the product fits a wish")
    relevance: float | None = Field(None, description="The search provider's relevance score for this page, 0..1")
    in_stock: bool | None = Field(None, description="What the store's page says; None = it did not say (sold-out items are never returned)")
    attributes: dict[str, str] = Field(default_factory=dict, description="Facts the page states about the product: color, fabric")
    rating: float | None = None
    reviews: int | None = None
    delivery: str | None = Field(None, description="e.g. 'Free delivery by Wed'")
    extraction: Literal["store_page"] = "store_page"  # the facts were read from the store's own product page


class ToolWarning(BaseModel):
    code: str = Field(description="machine-readable, e.g. RETAILER_NOT_ALLOWED")
    message: str
    count: int = 1


class SearchProductsResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    results: list[ProductResult]
    query_used: str = Field(description="The exact search text sent to the provider")
    store_groups: list[str] = Field(default_factory=list, description="The store groups that were searched")
    stores_searched: int = Field(0, description="How many approved stores the one search covered")
    pages_read: int = Field(0, description="How many candidate store pages were read for their price, image and stock")
    credits_spent: int = Field(0, description="Search credits this call cost (0 when served from cache)")
    from_cache: bool = Field(description="True if served from cache (no search credit spent)")
    warnings: list[ToolWarning] = Field(default_factory=list)


class StoreOffer(BaseModel):
    store: str = Field(description="Store name, e.g. 'Myntra'")
    url: str = Field(description="The store's own product page")
    price_inr: int | None = None
    in_stock: bool | None = Field(None, description="None = the listing did not say")
    details: list[str] = Field(default_factory=list, description="e.g. 'Free delivery', '14-day returns'")
    domain_allowed: bool = Field(description="False if the host is not on our allow-list")


class BuyLinkResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    product_id: str
    primary: StoreOffer | None = Field(None, description="The store's own page for this product")
    offers: list[StoreOffer]
    from_cache: bool
    warnings: list[ToolWarning] = Field(default_factory=list)


class LinkCheckResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    url: str
    final_url: str = Field(description="Where the link ends up after redirects")
    verdict: Literal["live", "dead", "unverified"] = Field(
        description="unverified = we could not tell (e.g. the store blocks automated checks)"
    )
    reason: Literal[
        "ok", "not_found", "gone", "soft_404", "bot_blocked", "server_error", "timeout",
        "connection_error", "redirected_off_domain", "too_many_redirects",
    ]
    status: int | None = Field(None, description="Final HTTP status, if a response was received")
    checked_at: str
