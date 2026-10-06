import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Category = Literal["top", "bottom"]

_NOT_STATED = {"", "none", "null", "n/a", "unknown", "not stated"}


class GarmentWish(BaseModel):
    """What the shopper asked for in ONE piece (the top or the bottom). Only what they actually said is set."""

    item: str | None = Field(None, description="the garment name only, e.g. 't-shirt', 'jeans', 'chinos'")
    color: str | None = Field(None, description="a colour the shopper named for this piece, e.g. 'white'")
    fit: str | None = Field(None, description="e.g. 'oversized', 'baggy', 'slim'")
    fabric: str | None = Field(None, description="e.g. 'denim', 'linen', 'cotton'")

    @field_validator("item", "color", "fit", "fabric", mode="before")
    @classmethod
    def _blank_means_not_stated(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in _NOT_STATED else v

    @property
    def is_empty(self) -> bool:
        return not (self.item or self.color or self.fit or self.fabric)


class PrefsExtraction(BaseModel):
    """What the LLM could read from the conversation. None means 'not stated yet'."""

    budget_inr: int | None = Field(None, description="Total outfit budget in INR")
    occasion: str | None = Field(None, description="e.g. college, office, party, casual")
    requests: str | None = Field(
        None,
        description="Wishes about the look or garments, in the shopper's words, e.g. 'suits, navy, no black'",
    )
    top: GarmentWish | None = Field(None, description="what the shopper asked for in the top, if anything")
    bottom: GarmentWish | None = Field(None, description="what the shopper asked for in the bottom, if anything")
    avoid: list[str] | None = Field(None, description="colours the shopper does not want, e.g. ['black']")

    @field_validator("top", "bottom", mode="before")
    @classmethod
    def _no_wish_is_none(cls, v):
        """Models write 'none' or an empty object when the shopper said nothing about a piece."""
        if isinstance(v, str) or (isinstance(v, dict) and not any(v.values())):
            return None
        return v

    @field_validator("avoid", mode="before")
    @classmethod
    def _avoid_as_list(cls, v):
        if isinstance(v, str):
            v = [x for x in re.split(r"[,;]| and ", v) if x.strip()]
        if isinstance(v, list):
            v = [str(x).strip().lower() for x in v if str(x).strip().lower() not in _NOT_STATED]
        return v or None

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
    color: str | None = Field(
        None,
        description="colour to search for. The planner picks it for coordination and it is never shown or "
        "checked; a colour the SHOPPER asked for (color_source='user') is searched, checked and shown",
    )
    color_source: Literal["planner", "user", "style", "anchor"] = Field(
        "planner",
        description="who chose the colour: 'user' (the shopper asked) and 'style' (the style card they picked names it) "
        "are verified against the product; the planner's own colours are only a hint",
    )
    fit: str | None = None
    fabric: str | None = None
    max_price_inr: int
    store_groups: list[str] = Field(
        default_factory=list,
        description="which groups of approved stores to search for this garment (set by code from the planner's "
        "choice; the tool searches ALL of those stores with one search)",
    )
    fixed: list[str] = Field(
        default_factory=list,
        description="which of item/color/fit/fabric the SHOPPER asked for (the rest are the planner's own choices)",
    )
    loose: list[str] = Field(
        default_factory=list,
        description="fit/fabric the PLANNER suggested (not the shopper): they steer the search but never reject a product",
    )
    avoid_colors: list[str] = Field(default_factory=list, description="colours the shopper does not want")
    keywords: str | None = Field(None, description="extra search words for a second try (set by the product reader)")
    style: str | None = Field(None, description="the look the shopper chose, passed to the search so it reads for pieces that suit it")


class OutfitSpec(BaseModel):
    top: ItemSpec
    bottom: ItemSpec
    rationale: str = Field(description="why these two pieces work together (garments only: never name colours)")


class OutfitPlan(BaseModel):
    outfits: list[OutfitSpec]
    store_groups: list[str] = Field(
        default_factory=list,
        description="the 1-3 groups of stores worth searching for this look, from the guide in the prompt "
        "(streetwear, smart_casual, denim, traditional, activewear)",
    )

    @field_validator("store_groups", mode="before")
    @classmethod
    def _only_known_groups(cls, v):
        """Models write 'None', a single string, or invented names: keep only real group ids."""
        from api.agent.stores import clean_groups

        if isinstance(v, str):
            v = [x for x in re.split(r"[,\s]+", v) if x]
        return clean_groups(v if isinstance(v, list) else [])


CheckStatus = Literal["match", "mismatch", "unknown"]


class AttributeCheck(BaseModel):
    """One requested attribute compared with what the product page actually says."""

    attribute: Literal["price", "category", "item", "color", "fit", "fabric", "gender", "avoid"]
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
    details: str = Field("", description="the product page's own description, read by the judge (never by the verifier)")
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="page-stated facts: color, fabric, fit, category (JSON-LD / breadcrumbs)",
    )
    mrp_inr: int | None = Field(None, description="list price before discount, if shown")
    in_stock: bool | None = Field(None, description="None = page did not say")
    available_sizes: list[str] = Field(default_factory=list)
    extraction: Literal["json_ld", "open_graph", "llm_fallback", "shopping_api", "tavily_page", "store_page"] | None = Field(
        None, description="how the fields were read; llm_fallback is the least trusted"
    )
    product_id: str | None = Field(None, description="opaque id from the search tool; used to get the buy link later")
    url_kind: Literal["google_product_page", "retailer"] | None = Field(
        None, description="'retailer' = the store's own page; 'google_product_page' = needs get_buy_link"
    )
    relevance: float | None = Field(None, description="the search provider's relevance score for this page, 0..1")
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
    spec: OutfitSpec | None = Field(None, description="the search spec that found this outfit (internal)")


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
    shopper_words: str = Field("", description="what the shopper asked for, in their own words (for the judge)")
    style: str = Field("", description="the chosen style, e.g. 'Korean casual: soft pastels, wide trousers'")


class FindProductsOutput(BaseModel):
    outfits: list[Outfit]  # each product carries its own `verification` comparison
    unfilled: list[UnfilledSpec]
    rejected: list[RejectedCandidate]  # candidates that failed verification, with reasons
    search_errors: list[str] = Field(
        default_factory=list, description="shopper-safe reasons any search could not run (limits, outage)"
    )


class CandidateVerdict(BaseModel):
    number: int = Field(description="the candidate's number as given")
    fits: Literal["yes", "no", "unsure"] = Field(description="does this product fit what the shopper asked for?")
    reason: str = Field("", description="one short line: what the decision is based on")

    @field_validator("fits", mode="before")
    @classmethod
    def _lenient(cls, v):
        v = str(v).strip().lower()
        return {"match": "yes", "true": "yes", "fit": "yes", "mismatch": "no", "false": "no", "unknown": "unsure",
                "maybe": "unsure", "unclear": "unsure"}.get(v, v)


class JudgeResult(BaseModel):
    """A reader's judgement of real, already-checked products against what the shopper asked for."""

    verdicts: list[CandidateVerdict]
    retry_keywords: str | None = Field(
        None, description="2-6 extra search words that would find better fits, only if too few fit"
    )

    @field_validator("retry_keywords", mode="before")
    @classmethod
    def _blank_keywords(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in _NOT_STATED else v


# ---- the conversation never ends: what the shopper's latest message means -----------------------------------
Intent = Literal["choose_style", "more_styles", "refine", "change_prefs", "new_request", "question", "unclear"]


class TurnIntent(BaseModel):
    """What the shopper's latest message is trying to do, given where the conversation is."""

    intent: Intent
    style: str | None = Field(
        None, description="for choose_style: the style named or described (a listed name, or their own words)"
    )

    @field_validator("style", mode="before")
    @classmethod
    def _blank_style(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in _NOT_STATED else v


class SlotEdit(BaseModel):
    """A change to ONE piece (the top or the bottom) of an outfit. Only fields the shopper mentioned are set."""

    keep: bool = Field(False, description="true if the shopper wants this piece kept as in the anchor outfit")
    item: str | None = Field(None, description="a different garment, e.g. 'chinos'")
    color: str | None = Field(None, description="a colour the SHOPPER asked for, e.g. 'purple'")
    fit: str | None = None
    fabric: str | None = None

    @field_validator("item", "color", "fit", "fabric", mode="before")
    @classmethod
    def _blank(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in _NOT_STATED else v


class RefinementEdit(BaseModel):
    """A shopper's change request after outfits were shown, as data. Code (not the model) applies it."""

    anchor: int | None = Field(
        None, description="number of the outfit they pointed at in the latest set ('the 3rd one' -> 3)"
    )
    relation: Literal["more_like", "replace", "tweak"] = Field(
        "tweak",
        description="more_like: new outfits similar to the anchor; replace: different from what was shown; "
        "tweak: the same idea with changes",
    )
    top: SlotEdit | None = None
    bottom: SlotEdit | None = None
    budget_inr: int | None = Field(None, description="a new total budget in rupees, only if a figure was stated")
    cheaper: bool = Field(False, description="they want lower prices but gave no figure")
    pricier: bool = Field(False, description="they want to spend more but gave no figure")
    note: str | None = Field(None, description="anything else they asked for, in their words (e.g. 'more formal')")

    @field_validator("budget_inr", mode="before")
    @classmethod
    def _amount(cls, v):
        if isinstance(v, str):
            m = re.search(r"(\d[\d,]*\.?\d*)\s*(k)?", v.lower())
            if not m:
                return None
            n = float(m.group(1).replace(",", ""))
            return int(n * 1000) if m.group(2) else int(n)
        return v

    @field_validator("note", mode="before")
    @classmethod
    def _blank_note(cls, v):
        return None if isinstance(v, str) and v.strip().lower() in _NOT_STATED else v


class AnswerOut(BaseModel):
    text: str = Field(description="a short, friendly answer based only on the facts provided")
