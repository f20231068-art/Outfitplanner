from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class StylistState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # reducer: append, never overwrite
    prefs: dict  # budget_inr, occasion, requests (menswear only, so no gender)
    missing: list[str]
    changed: list[str]  # preference names the latest message changed
    styles: list[dict]
    chosen_style: dict | None
    outfit_specs: list[dict]  # what plan_outfits wants searched
    store_groups: list[str]  # the groups of approved stores chosen for this look (one search covers a whole group)
    outfits: list[dict]  # validated outfits of THIS round (Outfit.model_dump())
    notes: list[str]  # feedback for the planner when a search came back weak
    rejected: list[dict]  # search candidates that failed verification, with reasons (debugging)
    search_errors: list[str]  # shopper-safe reasons a search could not run (limits, outage)
    retries: int
    # ---- the conversation never ends: these carry it from one message to the next ----
    phase: str  # gathering | choosing_style | outfits_shown
    pending_question: str | None  # what we asked, while phase == gathering
    shown: list[dict]  # every outfit ever shown, each tagged with its `round` (the latest round is what "outfit 3" means)
    round: int  # how many sets of outfits have been shown
    refinements: list[dict]  # every change the shopper asked for, as parsed (a record, and the "last intent")
    # ---- per-turn working fields, reset by route_turn at the start of every message ----
    choice: str | None  # a style card the shopper clicked (id), set by the API
    intent: str | None
    style_text: str | None
    edit: dict | None  # the parsed refinement being applied
    anchor: dict | None  # the outfit the shopper pointed at
    proceed: bool
