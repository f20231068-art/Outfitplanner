"""The data contract of the tools. FastMCP turns these into the JSON Schemas clients see."""

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1"


class ProductResult(BaseModel):
    """One candidate product, exactly as the shopping data reports it (nothing invented)."""

    product_id: str = Field(description="Opaque id; pass to get_buy_link to get the store's own URL")
    title: str
    retailer: str = Field(description="Store name as listed, e.g. 'Myntra'")
    price_inr: int = Field(description="Selling price in whole rupees")
    mrp_inr: int | None = Field(None, description="List price before discount, if shown")
    url: str = Field(description="Link to the product. See url_kind for what kind of link it is")
    url_kind: Literal["google_product_page", "retailer"] = Field(
        description="'google_product_page' = a Google Shopping page listing the stores; "
        "'retailer' = the store's own page"
    )
    image_url: str = Field(description="Small product thumbnail")
    rating: float | None = None
    reviews: int | None = None
    delivery: str | None = Field(None, description="e.g. 'Free delivery by Wed'")
    extraction: Literal["shopping_api"] = "shopping_api"  # where the fields came from


class ToolWarning(BaseModel):
    code: str = Field(description="machine-readable, e.g. RETAILER_NOT_ALLOWED")
    message: str
    count: int = 1


class SearchProductsResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    results: list[ProductResult]
    query_used: str = Field(description="The exact search text sent to the provider")
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
    primary: StoreOffer | None = Field(
        None, description="Best offer: the store the product was listed under, else the first allowed store"
    )
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
