"""The API application.

    uv run uvicorn api.main:app --port 8000              (needs Postgres: docker compose up -d postgres)

`create_app` builds the app from parts, so tests can swap in a fake model, fake search and a
throwaway database without touching the network.

BACKEND_MODE=live   real chat model + real product search through the MCP tool server (default)
BACKEND_MODE=demo   deterministic offline stand-ins, for evals, dashboards and development.
                    Refused when ENVIRONMENT=prod.
"""

import hmac
import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastmcp import Client
from langgraph.checkpoint.postgres import PostgresSaver
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.agent.demo import ScriptedLLM
from api.agent.graph import build_graph
from api.agent.llm import get_llm
from api.agent.mcp_search import McpProductSearch
from api.agent.products import mock_search
from api.config import Settings, settings
from api.db import make_pool, migrate
from api.mcp_auth import ServiceTokenAuth
from api.routes import admin, auth, chat, products
from api.security.throttle import FailureCounter, SlidingWindow
from api.telemetry import (
    HTTP_REQUESTS,
    HTTP_SECONDS,
    InstrumentedLLM,
    InstrumentedSearch,
    RunStats,
    configure_logging,
    parse_trace_id,
    request_id_var,
    trace_id_var,
)

log = logging.getLogger("api")


class DemoTools:
    """Stands in for the tool server in demo mode (buy links need no real store)."""

    def __init__(self, user_id: str):
        self.user_id = user_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def call_tool(self, name: str, args: dict):
        if name == "get_buy_link":
            url = f"https://demo.invalid/product/{args['product_id']}"
            return SimpleNamespace(structured_content={"primary": {
                "store": "Demo Store", "url": url, "price_inr": None, "in_stock": None}})
        return SimpleNamespace(structured_content={"verdict": "unverified"})


def make_graph_factory(llm, search_for_user, saver):
    """(user_id, stats) -> a ready agent whose model and search calls are counted into `stats`."""

    def factory(user_id: str, stats: RunStats | None = None):
        stats = stats or RunStats()
        return build_graph(InstrumentedLLM(llm, stats), InstrumentedSearch(search_for_user(user_id), stats), saver)

    return factory


def create_app(
    cfg: Settings = settings,
    pool=None,
    graph_factory=None,
    tool_client_factory=None,
    run_migrations: bool = False,
) -> FastAPI:
    owns_pool = pool is None
    demo = cfg.backend_mode == "demo"
    if demo and cfg.environment == "prod":
        raise RuntimeError("BACKEND_MODE=demo is not allowed when ENVIRONMENT=prod.")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        if run_migrations:
            migrate(cfg.database_url)
        app.state.pool = pool or make_pool(cfg.database_url)
        app.state.saver_pool = None
        if graph_factory is None:
            # the conversation's saved state lives in Postgres, in tables LangGraph creates itself;
            # its checkpointer needs autocommit connections, so it gets a pool of its own
            app.state.saver_pool = make_pool(cfg.database_url, min_size=1, max_size=5, autocommit=True)
            saver = PostgresSaver(app.state.saver_pool)
            saver.setup()
            if demo:
                log.warning("BACKEND_MODE=demo: using the scripted model and mock products")
                app.state.graph_factory = make_graph_factory(ScriptedLLM(), lambda _uid: mock_search, saver)
            else:
                app.state.graph_factory = make_graph_factory(get_llm(), lambda uid: McpProductSearch(uid, cfg), saver)
        else:
            app.state.graph_factory = graph_factory
        app.state.tool_client_factory = tool_client_factory or (
            DemoTools if demo else (lambda user_id: Client(cfg.mcp_url, auth=ServiceTokenAuth(user_id, cfg), timeout=30))
        )
        yield
        if app.state.saver_pool is not None:
            app.state.saver_pool.close()
        if owns_pool:
            app.state.pool.close()

    app = FastAPI(
        title="AI Stylist API", lifespan=lifespan,
        docs_url=None if cfg.environment == "prod" else "/docs",
        redoc_url=None, openapi_url=None if cfg.environment == "prod" else "/openapi.json",
    )

    # ---- shared state: settings and the rate limiters --------------------------------------------
    app.state.cfg = cfg
    app.state.login_failures = FailureCounter(cfg.login_max_failures, cfg.login_window_s)
    app.state.ip_limiter = SlidingWindow(30, 60)  # any one address: 30 auth calls a minute
    app.state.chat_limiter = SlidingWindow(cfg.chat_messages_per_min, 60)
    app.state.buy_limiter = SlidingWindow(cfg.buy_links_per_min, 60)
    for name, limiter in (("ip", app.state.ip_limiter), ("chat", app.state.chat_limiter), ("buy_link", app.state.buy_limiter)):
        limiter.name = name  # shows up in the rate-limit metric
    app.state.active_conversations = set()
    app.state.active_lock = threading.Lock()

    # ---- middleware ---------------------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware, allow_origins=[cfg.web_origin], allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "traceparent", "X-Trace-Id"],
        expose_headers=["X-Request-ID", "X-Trace-Id"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex[:16]  # lets one request be followed through the logs
        # If the caller (Mastra) sent a W3C trace id, adopt it so its trace, our logs and our audit
        # entries all share one id. A malformed one is ignored and we make our own.
        trace_id = parse_trace_id(request.headers.get("traceparent"), request.headers.get("x-trace-id")) or uuid.uuid4().hex
        request.state.request_id, request.state.trace_id = request_id, trace_id
        request_id_var.set(request_id)
        trace_id_var.set(trace_id)

        response = await call_next(request)

        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")  # '/conversations/{conversation_id}', never the raw id
        HTTP_REQUESTS.labels(request.method, template, str(response.status_code)).inc()
        HTTP_SECONDS.labels(template).observe(time.perf_counter() - started)
        if template != "/metrics":
            log.info("%s %s -> %s in %dms", request.method, template, response.status_code,
                     round((time.perf_counter() - started) * 1000))

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"  # tokens must never sit in a cache
        return response

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)

    # ---- routes -------------------------------------------------------------------------------------
    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}  # no login needed and nothing to learn from it

    @app.get("/metrics", include_in_schema=False)
    def metrics(request: Request) -> Response:
        """Prometheus scrapes this. Off unless METRICS_TOKEN is set, and then it needs that token, because
        counters describe our traffic and should not be public."""
        token = request.app.state.cfg.metrics_token
        if not token:
            return JSONResponse({"detail": "Not found."}, status_code=404)
        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(sent.encode(), token.encode()):
            return JSONResponse({"detail": "Unauthorized."}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(products.router)
    app.include_router(admin.router)
    return app


app = create_app(run_migrations=True)
