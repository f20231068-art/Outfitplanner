"""What the API measures about itself: trace ids, per-turn statistics, metrics and JSON logs.

Three kinds of signal, for three questions:
  Traces   "what happened in THIS request, step by step?"   (the trace id ties Mastra, API and audit log)
  Metrics  "how is the system doing overall?"                (Prometheus counters and histograms)
  Logs     "what exactly did it say?"                        (one JSON object per line, tagged with the ids)

Nothing here ever records message text, product details, tokens or keys: only ids, names and numbers.
"""

import contextvars
import json
import logging
import re
import time
from dataclasses import dataclass, field

from prometheus_client import Counter, Gauge, Histogram

# ---- trace ids --------------------------------------------------------------------------------------
_TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


def parse_trace_id(traceparent: str | None, x_trace_id: str | None = None) -> str | None:
    """The caller's trace id, from the standard W3C `traceparent` header or a plain `X-Trace-Id`.
    Anything malformed is ignored (never trusted, never echoed): we then make our own."""
    if traceparent and (m := _TRACEPARENT.match(traceparent.strip().lower())) and m[1] != "0" * 32:
        return m[1]
    if x_trace_id and _HEX32.match(x_trace_id.strip().lower()) and x_trace_id.strip("0") != "":
        return x_trace_id.strip().lower()
    return None


request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


# ---- per-turn statistics ------------------------------------------------------------------------------
@dataclass
class RunStats:
    """Counts for one chat turn. Plain numbers, safe to send to the browser and to Mastra."""

    llm_calls: int = 0
    llm_seconds: float = 0.0
    searches: int = 0
    search_seconds: float = 0.0
    search_errors: int = 0
    stages: list[dict] = field(default_factory=list)  # [{"stage": ..., "duration_ms": ...}]

    def as_dict(self) -> dict:
        return {
            "llm_calls": self.llm_calls, "llm_ms": round(self.llm_seconds * 1000),
            "searches": self.searches, "search_ms": round(self.search_seconds * 1000),
            "search_errors": self.search_errors,
        }


class InstrumentedLLM:
    """Wraps the chat model: counts and times every structured-output call (one per agent step)."""

    def __init__(self, inner, stats: RunStats):
        self._inner, self._stats = inner, stats
        self.model_name = getattr(inner, "model_name", type(inner).__name__)

    def with_structured_output(self, schema, **kwargs):
        runner = self._inner.with_structured_output(schema, **kwargs)
        stats = self._stats

        class Timed:
            def invoke(self, messages):
                start = time.perf_counter()
                try:
                    return runner.invoke(messages)
                finally:
                    stats.llm_calls += 1
                    stats.llm_seconds += time.perf_counter() - start
                    LLM_CALLS.inc()
                    LLM_SECONDS.observe(time.perf_counter() - start)

        return Timed()


class InstrumentedSearch:
    """Wraps the product search: counts and times every call, and every failure."""

    def __init__(self, inner, stats: RunStats):
        self._inner, self._stats = inner, stats

    def __call__(self, spec):
        start = time.perf_counter()
        try:
            return self._inner(spec)
        except Exception:
            self._stats.search_errors += 1
            raise
        finally:
            elapsed = time.perf_counter() - start
            self._stats.searches += 1
            self._stats.search_seconds += elapsed
            SEARCHES.inc()


# ---- Prometheus metrics ---------------------------------------------------------------------------------
HTTP_REQUESTS = Counter("stylist_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_SECONDS = Histogram("stylist_http_request_seconds", "HTTP request time", ["route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120))
CHAT_TURNS = Counter("stylist_chat_turns_total", "Chat turns by outcome", ["outcome"])
CHAT_TURN_SECONDS = Histogram("stylist_chat_turn_seconds", "Time to finish a chat turn",
                              buckets=(1, 2.5, 5, 10, 20, 30, 45, 60, 90, 120, 180))
STAGE_SECONDS = Histogram("stylist_stage_seconds", "Time per agent step", ["stage"],
                          buckets=(0.05, 0.25, 1, 2.5, 5, 10, 20, 40, 80))
OUTFITS_DELIVERED = Counter("stylist_outfits_delivered_total", "Outfits shown to shoppers")
OUTFIT_CONFIDENCE = Counter("stylist_outfits_by_confidence_total", "Outfits by colour confidence", ["confidence"])
LLM_CALLS = Counter("stylist_llm_calls_total", "Chat-model calls")
LLM_SECONDS = Histogram("stylist_llm_call_seconds", "Chat-model call time",
                        buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 45, 90))
SEARCHES = Counter("stylist_product_searches_total", "Product searches requested")
LOGINS = Counter("stylist_logins_total", "Login attempts", ["outcome"])
RATE_LIMITED = Counter("stylist_rate_limited_total", "Requests refused by a rate limit", ["limiter"])
ACTIVE_TURNS = Gauge("stylist_active_chat_turns", "Chat turns running right now")
BUY_LINKS = Counter("stylist_buy_links_total", "Buy-link lookups", ["outcome"])


# ---- JSON logging ------------------------------------------------------------------------------------------
class JsonFormatter(logging.Formatter):
    """One JSON object per line. Includes the request and trace ids so a log line can be matched to a
    trace in Jaeger/Mastra and to an audit-log entry. Exception text is kept; request bodies never are."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"), "level": record.levelname,
            "logger": record.name, "msg": record.getMessage(),
            "request_id": request_id_var.get(), "trace_id": trace_id_var.get(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request lines can contain API keys
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # we log requests ourselves
