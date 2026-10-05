"""Conversations: start one, send messages, watch the agent work, read history.

A conversation is the LangGraph "thread". Its state (preferences, styles, outfits shown...) is saved in
Postgres after every step. The conversation never ends: every message, typed or a clicked style card, is a new
turn that the agent routes from the saved state, so the shopper can always answer, change their mind, ask for
changes ("cheaper", "more like outfit 2") or ask a question.

POST /conversations/{id}/messages answers with a stream of server-sent events:
  status     a step finished       {"stage": "...", "label": "Stores searched"}
  outfits    the finished outfits  {"outfits": [...]}              (only when this turn found new ones)
  message    the agent's reply     {"role": "assistant", "text": "..."}
  pending    what is on offer now  {"type": "ask", "question": ...} | {"type": "choose_style", "styles": [...]} | null
  error      something failed      {"message": "..."}            (always safe to show)
  done       the turn is over
"""

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
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
    "set_style": "Style chosen",
    "refine": "Understood your change",
    "plan_outfits": "Outfits designed",
    "find_products": "Stores searched",
    "rank_and_validate": "Every item checked against your request",
    "answer_question": "Answered your question",
    "respond": "All done",
}


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    style_id: str | None = Field(None, max_length=64, description="a clicked style card (skips interpreting the text)")

    @field_validator("text")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Say something first.")
        return v


HEARTBEAT_S = 10  # a quiet stream gets a keep-alive this often
BEAT = object()  # what stream_with_heartbeat yields while the work is still running and nothing new has arrived
KEEP_ALIVE = ": still working\n\n"  # an SSE comment: clients ignore it, but proxies see the connection is alive


def stream_with_heartbeat(
    make_iter: Callable[[], Iterable], on_finish: Callable[[], None], interval: float = HEARTBEAT_S
) -> Iterator:
    """Run a slow, blocking iterator in a worker thread and yield its items; yield BEAT whenever `interval` seconds
    pass with nothing new.

    Why: one agent turn can be silent for a minute (a model call, then searches). A proxy or load balancer between
    the browser and the API may drop a connection that is silent that long, so the shopper would lose the reply.
    `on_finish` runs when the work itself ends (even if the browser has gone), so the conversation stays marked
    busy exactly as long as the agent is really still working on it."""
    box: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            for item in make_iter():
                box.put(("item", item))
        except Exception as exc:  # noqa: BLE001 - not swallowed: handed to the consumer, which re-raises it as a safe error event
            box.put(("error", exc))
        finally:
            on_finish()
            box.put(("end", None))

    threading.Thread(target=work, daemon=True, name="chat-turn").start()
    while True:
        try:
            kind, value = box.get(timeout=interval)
        except queue.Empty:
            yield BEAT
            continue
        if kind == "end":
            return
        if kind == "error":
            raise value
        yield value


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


def pending_from_values(values: dict) -> dict | None:
    """What the shopper is being offered right now, read from the saved state (there is no paused graph)."""
    phase = values.get("phase")
    if phase == "gathering" and values.get("pending_question"):
        return {"type": "ask", "question": values["pending_question"]}
    if phase == "choosing_style" and values.get("styles"):
        return {"type": "choose_style", "styles": values["styles"]}
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
        cap = s.cfg.daily_conversations_per_user
        if cap > 0 and repo.conversations_today(conn, who.user_id) >= cap:
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
        "messages": _messages(snapshot), "pending": pending_from_values(snapshot.values),
        "phase": snapshot.values.get("phase"), "outfits": outfits,
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
    earlier = snapshot.values.get("messages", [])
    payload = {"messages": [("user", body.text)], "choice": body.style_id}
    request_id = getattr(request.state, "request_id", None)
    trace_id = getattr(request.state, "trace_id", None)

    with s.pool.connection() as conn:
        repo.touch_conversation(conn, cid, title=None if earlier else body.text[:60])
        # the audit log records THAT a message was sent, never what it said. The trace id links this
        # entry to the trace (Mastra / Jaeger) of the same request.
        audit.append(conn, who.user_id, "message_sent", {
            "conversation": cid, "length": len(body.text), "phase": snapshot.values.get("phase"),
            "request_id": request_id, "trace_id": trace_id,
        })

    def events():
        finished, outcome, delivered = False, "ok", []  # finished: did this turn deliver a new set of outfits
        started = last_mark = time.perf_counter()
        ACTIVE_TURNS.inc()
        def release() -> None:  # the agent is done with this conversation (or failed): allow the next message
            with s.active_lock:
                s.active_conversations.discard(cid)

        try:
            for update in stream_with_heartbeat(lambda: graph.stream(payload, config, stream_mode="updates"), release):
                if update is BEAT:
                    yield KEEP_ALIVE
                    continue
                now = time.perf_counter()
                for node in update:
                    if node in STAGE_LABELS:
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
            values = graph.get_state(config).values
            if finished:
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
            reply = next((m for m in reversed(values.get("messages", [])[len(earlier) + 1:]) if m.type == "ai"), None)
            if reply is not None:
                yield sse("message", {"role": "assistant", "text": str(reply.content)})
            pending = pending_from_values(values)
            if pending is not None and not finished:
                outcome = "waiting_for_user"  # the turn ended by asking a question or offering style cards
            yield sse("pending", pending)
        except GeneratorExit:  # the connection was closed from the other end (the browser left, or a proxy gave up)
            log.warning("client connection closed %.1fs into the turn (request %s, trace %s)", time.perf_counter() - started, request_id, trace_id)
            raise
        except Exception as exc:
            outcome = "error"
            log.exception("chat turn failed (request %s)", request_id)
            with s.pool.connection() as conn:
                audit.append(conn, who.user_id, "chat_error", {
                    "conversation": cid, "type": type(exc).__name__, "trace_id": trace_id,
                })
            yield sse("error", {"message": _friendly(exc)})
        finally:  # runs even if the browser disconnects mid-stream (the worker thread frees the conversation itself)
            ACTIVE_TURNS.dec()
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
