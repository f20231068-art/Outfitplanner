import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Category = Literal["top", "bottom"]

_NOT_STATED = {"", "none", "null", "n/a", "unknown", "not stated"}


class PrefsExtraction(BaseModel):
    """What the LLM could read from the conversation. None means 'not stated yet'."""

    budget_inr: int | None = Field(None, description="Total outfit budget in INR")
    occasion: str | None = Field(None, description="e.g. college, office, party, casual")
    requests: str | None = Field(
        None,
        description="Wishes about the look or garments, in the shopper's words, e.g. 'suits, navy, no black'",
    )

    @field_validator("budget_inr", "occasion", "requests", mode="before")
    @classmethod
    def _blank_means_not_stated(cls, v):
        """Models sometimes write 'None' / 'null' / 'unknown' as text instead of a real null."""
        if isinstance(v, str) and v.strip().lower() in _NOT_STATED:
            return None
        return v

    @field_validator("budget_inr", mode="before")
    @classmethod
    def _parse_amount(cls, v):
        """Accept '4000', '4,000', 'Rs 4k' and '₹4000' as well as plain integers."""
        if isinstance(v, str):
            m = re.search(r"(\d[\d,]*\.?\d*)\s*(k)?", v.lower())
            if not m:
                return None
            n = float(m.group(1).replace(",", ""))
            return int(n * 1000) if m.group(2) else int(n)
        return v


class StyleOption(BaseModel):
    id: str = Field(description="short slug, e.g. 'korean-casual'")
    name: str
    description: str = Field(description="one line a shopper understands")
    image_prompt: str = Field(description="prompt for a style preview image (no real people)")


class StyleList(BaseModel):
    styles: list[StyleOption]


class ItemSpec(BaseModel):
    """Exact thing to search for. This is the contract with search_products."""

    category: Category
    item: str = Field(description="e.g. 't-shirt', 'baggy pants'")
    color: str
    fit: str | None = None
    fabric: str | None = None
    max_price_inr: int


class OutfitSpec(BaseModel):
    top: ItemSpec
    bottom: ItemSpec
    rationale: str = Field(description="why these colours and pieces work together")


class OutfitPlan(BaseModel):
    outfits: list[OutfitSpec]


CheckStatus = Literal["match", "mismatch", "unknown"]


class AttributeCheck(BaseModel):
    """One requested attribute compared with what the product page actually says."""

    attribute: Literal["price", "category", "item", "color", "fit", "fabric", "gender"]
    requested: str
    found: str | None = Field(None, description="value read from the product data, never invented")
    status: CheckStatus
    evidence: str | None = Field(None, description="the field or text the verdict is based on")
    required: bool = Field(description="if True, anything but 'match' rejects the product")
    assumed: bool = Field(
        False,
        description="no evidence found, so the value is trusted from the search query (low confidence)",
    )


class MatchReport(BaseModel):
    is_match: bool
    confidence: Literal["high", "low"] = Field(
        "high", description="low when any attribute was assumed from the query, not read from data"
    )
    score: float = Field(description="share of checks that matched, 0..1")
    checks: list[AttributeCheck]
    blocking: list[str] = Field(default_factory=list, description="attributes that caused rejection")


class Product(BaseModel):
    """Raw product data as scraped. Every field comes from the page, never from an LLM."""

    title: str
    retailer: str
    price_inr: int
    url: str
    image_url: str
    color: str | None = None
    description: str = ""
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="page-stated facts: color, fabric, fit, category (JSON-LD / breadcrumbs)",
    )
    mrp_inr: int | None = Field(None, description="list price before discount, if shown")
    in_stock: bool | None = Field(None, description="None = page did not say")
    available_sizes: list[str] = Field(default_factory=list)
    extraction: Literal["json_ld", "open_graph", "llm_fallback", "shopping_api"] | None = Field(
        None, description="how the fields were read; llm_fallback is the least trusted"
    )
    product_id: str | None = Field(None, description="opaque id from the search tool; used to get the buy link later")
    url_kind: Literal["google_product_page", "retailer"] | None = Field(
        None, description="'retailer' = the store's own page; 'google_product_page' = needs get_buy_link"
    )
    rating: float | None = None
    reviews: int | None = None
    delivery: str | None = None
    fetched_at: str | None = Field(None, description="ISO time the page was read (prices go stale)")
    verification: MatchReport | None = None  # filled in by verify_product


class Outfit(BaseModel):
    top: Product
    bottom: Product
    total_inr: int
    rationale: str
    confidence: Literal["high", "low"] = "high"  # low if either item has an assumed attribute


class RejectedCandidate(BaseModel):
    title: str
    retailer: str
    url: str
    reasons: list[str]


class UnfilledSpec(BaseModel):
    spec_index: int
    item: str
    reason: str


class FindProductsInput(BaseModel):
    """The app is menswear only, so every search and check assumes a male adult shopper."""

    specs: list[OutfitSpec]
    budget_inr: int
    exclude_urls: list[str] = Field(
        default_factory=list, description="products already used in earlier outfits"
    )


class FindProductsOutput(BaseModel):
    outfits: list[Outfit]  # each product carries its own `verification` comparison
    unfilled: list[UnfilledSpec]
    rejected: list[RejectedCandidate]  # candidates that failed verification, with reasons
    search_errors: list[str] = Field(
        default_factory=list, description="shopper-safe reasons any search could not run (limits, outage)"
    )
