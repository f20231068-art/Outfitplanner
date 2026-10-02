"""What the tool server measures about itself (Prometheus). Numbers and names only: never arguments,
product data, user ids, tokens or keys, so scraping it cannot leak anything about shoppers."""

import time
from collections.abc import Iterator
from contextlib import contextmanager

from fastmcp.exceptions import ToolError
from prometheus_client import Counter, Histogram

TOOL_CALLS = Counter("mcp_tool_calls_total", "Tool calls", ["tool", "outcome"])
TOOL_SECONDS = Histogram("mcp_tool_seconds", "Tool call time", ["tool"],
                         buckets=(0.005, 0.05, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40))
CACHE = Counter("mcp_cache_total", "Cache lookups", ["tool", "result"])
CREDITS = Counter("mcp_search_credits_spent_total", "Paid search-provider calls", ["kind"])
LIMIT_HITS = Counter("mcp_limit_hits_total", "Calls refused by a limit", ["limit"])
AUTH_REFUSALS = Counter("mcp_auth_refusals_total", "Requests refused at the door", ["reason"])


@contextmanager
def tracked(tool: str) -> Iterator[None]:
    """Count and time one tool call. ToolError means we refused or failed on purpose (limits, bad
    input, provider trouble); any other exception is a bug."""
    start = time.perf_counter()
    outcome = "ok"
    try:
        yield
    except ToolError:
        outcome = "refused"
        raise
    except Exception:
        outcome = "error"
        raise
    finally:
        TOOL_CALLS.labels(tool, outcome).inc()
        TOOL_SECONDS.labels(tool).observe(time.perf_counter() - start)
