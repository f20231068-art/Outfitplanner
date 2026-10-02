from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class StylistState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]  # reducer: append, never overwrite
    prefs: dict  # budget_inr, occasion (menswear only, so no gender)
    missing: list[str]
    styles: list[dict]
    chosen_style: dict | None
    outfit_specs: list[dict]  # what plan_outfits wants searched
    outfits: list[dict]  # validated outfits (Outfit.model_dump())
    notes: list[str]  # feedback for the planner when a search came back weak
    rejected: list[dict]  # search candidates that failed verification, with reasons (debugging)
    search_errors: list[str]  # shopper-safe reasons a search could not run (limits, outage)
    retries: int
