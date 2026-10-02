"""Conversations: start one, send messages, watch the agent work, read history.

A conversation is the LangGraph "thread". Its state (budget, styles, outfits...) is saved in
Postgres after every step, so the user can answer a question hours later and the agent resumes.

POST /conversations/{id}/messages answers with a stream of server-sent events:
  status     a step finished       {"stage": "...", "label": "Stores searched"}
  interrupt  the agent needs input {"type": "ask" | "choose_style", ...}
  outfits    the finished outfits  {"outfits": [...]}
  message    the agent's reply     {"role": "assistant", "text": "..."}
  error      something failed      {"message": "..."}            (always safe to show)
  done       the turn is over
"""

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api import audit, repo
from api.deps import current_user, enforce, sse
from api.security.tokens import Identity
from api.telemetry import (
    ACTIVE_TURNS,
    CHAT_TURN_SECONDS,
    CHAT_TURNS,
    OUTFIT_CONFIDENCE,
    OUTFITS_DELIVERED,
    STAGE_SECONDS,
    RunStats,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["chat"])

# What each finished step means to the shopper
STAGE_LABELS = {
    "gather_prefs": "Understood your request",
    "propose_styles": "Styles ready",
    "plan_outfits": "Outfits designed",
    "find_products": "Stores searched",
    "rank_and_validate": "Every item checked against your request",
    "respond": "All done",
}
# Starting a new round in a finished conversation: forget the previous round's working data
FRESH_ROUND = {
    "outfits": [], "outfit_specs": [], "notes": [], "retries": 0, "search_errors": [],
    "styles": [], "chosen_style": None,
}


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Say something first.")
        return v


def _valid_id(conversation_id: str) -> str:
    try:
        return str(uuid.UUID(conversation_id))
    except ValueError:
        raise HTTPException(404, "Conversation not found.") from None


def _owned(request: Request, who: Identity, conversation_id: str) -> dict:
    cid = _valid_id(conversation_id)
    with request.app.state.pool.connection() as conn:
        row = repo.get_conversation(conn, cid, who.user_id)
    if row is None:  # also what someone else's conversation looks like: not revealed to exist
        raise HTTPException(404, "Conversation not found.")
    return row


def pending_interrupt(snapshot) -> dict | None:
    for task in snapshot.tasks:
        for it in task.interrupts:
            return it.value
    return None


def _messages(snapshot) -> list[dict]:
    return [
        {"role": "user" if m.type == "human" else "assistant", "text": str(m.content)}
        for m in snapshot.values.get("messages", [])
    ]


@router.post("", status_code=201)
def create(request: Request, who: Identity = Depends(current_user)):
    s = request.app.state
    with s.pool.connection() as conn:
        if repo.conversations_today(conn, who.user_id) >= s.cfg.daily_conversations_per_user:
            raise HTTPException(429, "You have reached today's limit for new conversations. Try again tomorrow.")
        row = repo.create_conversation(conn, who.user_id)
        audit.append(conn, who.user_id, "conversation_created", {"conversation": str(row["id"])})
    return {"id": str(row["id"]), "title": row["title"]}


@router.get("")
def list_all(request: Request, who: Identity = Depends(current_user)):
    with request.app.state.pool.connection() as conn:
        rows = repo.list_conversations(conn, who.user_id)
    return [{"id": str(r["id"]), "title": r["title"], "updated_at": r["updated_at"].isoformat()} for r in rows]


@router.get("/{conversation_id}")
def history(conversation_id: str, request: Request, who: Identity = Depends(current_user)):
    row = _owned(request, who, conversation_id)
    s = request.app.state
    snapshot = s.graph_factory(who.user_id, None).get_state({"configurable": {"thread_id": str(row["id"])}})
    with s.pool.connection() as conn:
        outfits = repo.outfits_for_conversation(conn, str(row["id"]), who.user_id)
    return {
        "id": str(row["id"]), "title": row["title"],
        "messages": _messages(snapshot), "pending": pending_interrupt(snapshot), "outfits": outfits,
    }


def _friendly(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "ratelimit" in name or "429" in str(exc):
        return "The assistant is busy right now. Please try again in a minute."
    if "timeout" in name or "connect" in name:
        return "The assistant took too long to answer. Please try again."
    return "Something went wrong on our side. Please try again."


@router.post("/{conversation_id}/messages")
def send(conversation_id: str, body: MessageIn, request: Request, who: Identity = Depends(current_user)):
    row = _owned(request, who, conversation_id)
    cid = str(row["id"])
    s = request.app.state
    enforce(s.chat_limiter, who.user_id)

    with s.active_lock:  # one turn at a time per conversation
        if cid in s.active_conversations:
            raise HTTPException(409, "Still working on your previous message. Please wait a moment.")
        s.active_conversations.add(cid)

    stats = RunStats()
    graph = s.graph_factory(who.user_id, stats)
    config = {"configurable": {"thread_id": cid}}
    snapshot = graph.get_state(config)
    resuming = pending_interrupt(snapshot) is not None
    payload = Command(resume=body.text) if resuming else {"messages": [("user", body.text)], **FRESH_ROUND}
    request_id = getattr(request.state, "request_id", None)
    trace_id = getattr(request.state, "trace_id", None)

    with s.pool.connection() as conn:
        repo.touch_conversation(conn, cid, title=None if resuming else body.text[:60])
        # the audit log records THAT a message was sent, never what it said. The trace id links this
        # entry to the trace (Mastra / Jaeger) of the same request.
        audit.append(conn, who.user_id, "message_sent", {
            "conversation": cid, "length": len(body.text), "resuming": resuming,
            "request_id": request_id, "trace_id": trace_id,
        })

    def events():
        finished, outcome, delivered = False, "ok", []
        started = last_mark = time.perf_counter()
        ACTIVE_TURNS.inc()
        try:
            for update in graph.stream(payload, config, stream_mode="updates"):
                now = time.perf_counter()
                for node, value in update.items():
                    if node == "__interrupt__":
                        outcome = "waiting_for_user"
                        yield sse("interrupt", value[0].value)
                    elif node in STAGE_LABELS:
                        # steps run one after another, so the time since the previous update is this step's time
                        ms = round((now - last_mark) * 1000)
                        stats.stages.append({"stage": node, "duration_ms": ms})
                        STAGE_SECONDS.labels(node).observe(ms / 1000)
                        yield sse("status", {
                            "stage": node, "label": STAGE_LABELS[node], "duration_ms": ms,
                            "elapsed_ms": round((now - started) * 1000),
                        })
                        finished = finished or node == "respond"
                last_mark = now
            state = graph.get_state(config)
            if finished and pending_interrupt(state) is None:
                values = state.values
                with s.pool.connection() as conn:
                    if values.get("outfits"):
                        style = (values.get("chosen_style") or {}).get("name", "")
                        batch = repo.save_outfits(conn, who.user_id, cid, style, values["outfits"])
                        audit.append(conn, who.user_id, "outfits_delivered", {
                            "conversation": cid, "count": len(values["outfits"]), "batch": batch,
                            "trace_id": trace_id,
                        })
                    saved = repo.outfits_for_conversation(conn, cid, who.user_id)
                if values.get("outfits"):
                    delivered = [o for o in saved if o["batch"] == max(x["batch"] for x in saved)]
                    OUTFITS_DELIVERED.inc(len(delivered))
                    for o in delivered:
                        OUTFIT_CONFIDENCE.labels(o["confidence"]).inc()
                    yield sse("outfits", {"outfits": delivered})
                else:
                    outcome = "no_outfits"
                last = values["messages"][-1]
                yield sse("message", {"role": "assistant", "text": str(last.content)})
        except Exception as exc:
            outcome = "error"
            log.exception("chat turn failed (request %s)", request_id)
            with s.pool.connection() as conn:
                audit.append(conn, who.user_id, "chat_error", {
                    "conversation": cid, "type": type(exc).__name__, "trace_id": trace_id,
                })
            yield sse("error", {"message": _friendly(exc)})
        finally:  # runs even if the browser disconnects mid-stream, so the conversation is never stuck busy
            ACTIVE_TURNS.dec()
            with s.active_lock:
                s.active_conversations.discard(cid)
        elapsed = time.perf_counter() - started
        CHAT_TURNS.labels(outcome).inc()
        CHAT_TURN_SECONDS.observe(elapsed)
        yield sse("done", {
            "trace_id": trace_id, "outcome": outcome, "elapsed_ms": round(elapsed * 1000),
            "stats": stats.as_dict(), "outfit_count": len(delivered),
        })

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # do not let proxies buffer the stream
    )
