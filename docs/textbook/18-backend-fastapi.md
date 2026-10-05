# Chapter 18. Backend Engineering with FastAPI

> **Learning objectives.** Understand how an ASGI web service works (server, framework, event loop, thread pool); structure an application with factories, lifespan, routers, dependencies and middleware; validate input and shape output with Pydantic; stream responses; handle errors safely; test with dependency injection; reason about concurrency, workers and graceful shutdown; and read `services/api` completely.
>
> **Prerequisites.** Chapters 2, 16, 17.

---

## 18.1 From request to code: the stack

```
Browser/Caddy ──HTTP──► uvicorn (ASGI server) ──► Starlette (ASGI toolkit) ──► FastAPI (routing, validation, DI) ──► your functions
```

* **WSGI** (Flask, Django classic) is the older synchronous Python web interface: one request, one thread. **ASGI** is the modern asynchronous successor supporting `async`, **streaming, WebSockets, and long-lived connections**: essential for chat and SSE.
* **uvicorn** is an ASGI **server**: it listens on a socket, parses HTTP, calls the app, writes responses. (`uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers`: "import `app` from `api/main.py`".)
* **Starlette** provides requests/responses, routing, middleware, background tasks, streaming.
* **FastAPI** adds **type-hint-driven validation (Pydantic)**, **dependency injection**, **automatic OpenAPI docs**, and ergonomic routing.

### Sync versus async endpoints (get this exactly right)

* `async def` endpoints run **on the event loop**; they must **never block** (no `time.sleep`, no synchronous HTTP/DB calls, no heavy CPU), or every other request stalls.
* Plain `def` endpoints run in a **worker thread pool** (AnyIO's default limiter allows on the order of tens of threads; verify for your version), so blocking inside them is fine, up to the pool limit.

Which does this app use, and why?

| Endpoint | Style | Reason |
|---|---|---|
| `/auth/register`, `/auth/login`, `/auth/refresh` | `def` (sync) | **Argon2id hashing is deliberately CPU- and memory-heavy** (tens of ms); on the event loop it would freeze all other requests; in a threadpool thread it blocks only that thread. Also uses the sync psycopg pool |
| `POST /conversations/{id}/messages` | `def` + a **sync generator** | LangGraph's `stream` and psycopg calls are synchronous; Starlette iterates a sync generator in the thread pool |
| `POST /products/{id}/buy-link` | `async def` | awaits the async MCP client (`await tools.call_tool(...)`); database lookups here are quick `with pool.connection()` blocks |
| `GET /health` | `def` | trivial |

An important operational consequence (Chapter 5, Little's Law): **each in-flight chat turn occupies a thread for its whole duration** (tens of seconds), so thread-pool size bounds concurrent turns per process. Increase workers/processes or convert to a fully async pipeline for more.

## 18.2 Application structure

```
services/api/src/api/
  main.py          create_app(): builds the app from parts; module-level `app = create_app(run_migrations=True)`
  config.py        Settings (pydantic-settings)
  db.py            pool + migrations
  deps.py          dependencies: current_user, enforce (rate limit), client_ip, sse()
  repo.py          every SQL query for chat features
  accounts.py      account/session logic (plain functions over a connection)
  audit.py         hash-chained log
  mcp_auth.py      service-to-service tokens
  telemetry.py     metrics, logging, trace ids
  agent/           graph, state, schemas, verifier, find, llm, mcp_search, demo, prompts
  routes/          auth.py, chat.py, products.py, admin.py   (thin HTTP layer)
  security/        passwords.py, tokens.py, throttle.py
```

### Layering

| Layer | Knows about | Must not know about |
|---|---|---|
| **Routes** (HTTP) | requests, status codes, auth dependencies, response shape | SQL, hashing details, graph internals |
| **Services / domain** (`accounts`, `audit`, `agent/*`) | business rules | HTTP, FastAPI |
| **Repository** (`repo.py`) | SQL | business rules, HTTP |
| **Infrastructure** (`db`, `telemetry`, `mcp_auth`) | drivers and protocols | business rules |

Routes are **thin**: parse and validate, call a function, translate the outcome to HTTP. Business logic in plain functions is testable without a web server (`accounts.register(conn, ...)` is tested with a database connection only).

### The application factory

```python
def create_app(cfg=settings, pool=None, graph_factory=None, tool_client_factory=None, run_migrations=False) -> FastAPI:
    ...
    @asynccontextmanager
    async def lifespan(app): ...
    app = FastAPI(title="AI Stylist API", lifespan=lifespan, docs_url=None if cfg.environment == "prod" else "/docs", ...)
    ...
    return app

app = create_app(run_migrations=True)
```

**Why a factory?** It lets tests build an app with a throwaway pool, a fake model and fake search, and the production module builds the real one. **Honest observation**: the last line creates the app and (via lifespan) connects to the database *when the module is imported by uvicorn*. It is fine for a service, but an import with side effects makes tooling (documentation generators, some test setups) heavier; a common refinement is `uvicorn --factory api.main:create_app`.

### Lifespan: startup and shutdown

```python
@asynccontextmanager
async def lifespan(app):
    configure_logging()
    if run_migrations: migrate(cfg.database_url)
    app.state.pool = pool or make_pool(cfg.database_url)
    ... build the LangGraph saver and graph factory ...
    yield                                     # the app serves requests here
    app.state.saver_pool.close(); app.state.pool.close()      # shutdown: release connections cleanly
```

Everything before `yield` runs at startup (run migrations, open pools, create `PostgresSaver` tables via `saver.setup()`); everything after, at shutdown. **`app.state`** holds shared objects (pool, limiters, graph factory, settings); request handlers reach them via `request.app.state`. Initialise shared resources **once**, not per request.

### Settings and secrets

`Settings(BaseSettings)` reads environment variables with defaults; secrets come from the environment, never code (Chapter 2). **Production switches** driven by settings: `ENVIRONMENT=prod` disables `/docs` and `/openapi.json`; `COOKIE_SECURE=true`; demo mode refuses to start in prod. **Fail early**: missing keys raise on first use with an explicit message.

## 18.3 Request handling

### Pydantic models for bodies, FastAPI for wiring

```python
class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    @field_validator("text")
    @classmethod
    def not_blank(cls, v): v = v.strip(); ...; return v

@router.post("/{conversation_id}/messages")
def send(conversation_id: str, body: MessageIn, request: Request, who: Identity = Depends(current_user)):
```

FastAPI inspects the signature: `conversation_id` comes from the **path**, `body` from the **JSON body** (validated into `MessageIn`), `request` is the raw `Request`, `who` comes from a **dependency**. Invalid input produces an automatic **422** with details (the UI's `message()` helper extracts `detail[0].msg`); unknown JSON fields are rejected (`extra="forbid"`).

### `response_model`

`response_model=TokenResponse` makes FastAPI **filter and validate the output**: only declared fields leave the server. It prevents accidental leaks (returning an ORM object with a password hash) and documents the response.

### Status codes and errors

* `status_code=201` for creation; `HTTPException(status, detail, headers=...)` for errors.
* **Uniform, safe messages**: `current_user` always raises `HTTPException(401, "Please log in.")` regardless of *why* the token failed (`from None` hides the cause).
* **Existence-hiding 404s**: not-yours and not-found look identical (`_owned`, `buy_link`, `admin_only`).
* **A global handler** for unexpected exceptions:

```python
@app.exception_handler(Exception)
async def unexpected(request, exc):
    log.exception("unhandled error")                           # full stack to logs, with ids
    return JSONResponse({"detail": "Something went wrong on our side."}, status_code=500)
```

The user sees nothing internal; operators see everything in logs.

### Dependencies (FastAPI's dependency injection)

A **dependency** is a callable FastAPI runs *before* your endpoint, passing its return value in. They compose:

```python
def current_user(request: Request) -> Identity: ...        # parses and verifies the bearer token

def admin_only(request: Request, who: Identity = Depends(current_user)) -> Identity:
    ...                                                    # builds on current_user; 404 for non-admins

@router.get("/audit/verify")
def verify_audit(request: Request, _: Identity = Depends(admin_only)): ...
```

Benefits: **reuse** (auth in one place), **declarative security** (the signature *shows* what is required), and **testability** (tests can override dependencies: `app.dependency_overrides[current_user] = lambda: Identity("u1")`). The repo mostly tests through real tokens instead, exercising the actual auth path.

Another helper pattern: **`enforce(limiter, key)`** is a plain function (not a dependency) because the key (user id, IP) is computed in the handler.

### Rate limiting at the API layer

`SlidingWindow` instances live on `app.state`: per-IP (30 auth calls/min), per-user chat (10/min), per-user buy-link (10/min). `enforce` converts `TooManyAttempts` into **429 + `Retry-After`** and increments a metric. Limits are applied **after** authentication where the key is a user id (so unauthenticated floods cost you little) and **before** expensive work. Remember the limitation: *in-memory, per process*.

## 18.4 Middleware

Middleware wraps every request/response. The `request_context` middleware in `main.py` shows a complete, realistic example:

1. Generate a **request id**; adopt a validated caller **trace id** (else make one); store both on `request.state` and in `contextvars` for logs.
2. Call the next handler (`response = await call_next(request)`).
3. Record **metrics** with the route **template** and status; log one structured line (not for `/metrics`).
4. Add **response headers**: `X-Request-ID`, `X-Trace-Id`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, and `Cache-Control: no-store` for `/auth/*`.

Rules of thumb: **order matters** (middleware added later wraps earlier ones; CORS is typically outermost so even error responses get CORS headers); keep middleware **cheap**; avoid reading request bodies in middleware (it breaks streaming/consumption); be aware that Starlette's `@app.middleware("http")` (a `BaseHTTPMiddleware`) has subtleties with streaming responses, background tasks and context variables; pure ASGI middleware avoids them when it matters.

**CORS** is added with `CORSMiddleware` (Chapter 16): explicit origin, credentials, methods, headers.

## 18.5 Streaming responses

```python
return StreamingResponse(events(), media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`events()` is a **generator**; each `yield` becomes network data immediately. Checklist for correct streaming:

* **Headers**: `text/event-stream`, `no-cache`, and a hint to proxies not to buffer.
* **Do the authentication, validation and locking *before* starting to stream** (errors afterwards cannot change the status code; they must be sent as events). In `send`, all the 401/404/409/429 checks happen first; once streaming starts the status is 200 and failures arrive as an `error` event followed by `done`.
* **Always terminate** with a final event (`done`) so the client knows the turn ended even after an error.
* **Cleanup in `finally`**: disconnects close the generator; release locks and decrement gauges there.
* **Do not hold a database transaction open** across the stream: database writes happen in short blocks.
* **Heartbeats** if stages can be silent for long; **small events**; **JSON-safe framing**.

## 18.6 Authentication and authorisation in the API

The auth routes (`routes/auth.py`) implement a complete session system (Chapter 20 explains the cryptography):

* **register**: per-IP limit → validate email and password policy → insert user (unique violation → 409) → start a token family → audit → set the cookie → return an access token.
* **login**: per-IP limit → **lockout check** (5 failures per email+IP per 15 min) → authenticate (constant-ish time) → on failure record, audit, **commit**, 401 → on success clear failures, start session, audit.
* **refresh**: **CSRF header check** → IP limit → cookie → `rotate` (theft detection) → set new cookie → new access token; on `invalid` or `reuse` **delete the cookie** and 401.
* **logout**: CSRF header → revoke the token family → clear cookie → 204.
* **me**: dependency `current_user`, then a database check that the user still exists and is not disabled (a valid-but-stale token for a deleted user fails closed).

**Authentication** (who are you?) is the dependency; **authorisation** (may you do this?) is the *ownership query* (`WHERE id = %s AND user_id = %s`), the admin allow-list, and per-feature limits. **Always authorise at the object level**: checking only "is logged in" is the root of IDOR bugs (Chapter 21).

## 18.7 Errors, validation and idempotency checklist

* Validate **all inputs** with types and bounds: lengths (`max_length` on password and email), enums, UUID parsing (`_valid_id`), numeric ranges (`ge/le`).
* **Canonicalise before comparing** (lower-case emails).
* **Return the same response shape for expected failures**; keep error `detail` safe.
* **Protect non-idempotent actions**: the one-turn-per-conversation lock and `UNIQUE` constraints protect duplicate processing; for payments you would add idempotency keys.
* **Timeouts** on outbound calls; **bounded retries**.
* **Log with ids; never log secrets or content.**
* **Avoid information leaks** in timing and messages (the dummy-hash verification; uniform 401 and 404).

## 18.8 Testing the API

* **`TestClient`** (Starlette) calls the ASGI app in-process, no network: `with TestClient(app, base_url="http://localhost") as client:` (using the context manager runs the lifespan).
* **Fixtures**: a **fresh migrated database per test** (`make_database`), a `pool`, an `env` fixture building `create_app(make_cfg(), pool=pool, graph_factory=..., tool_client_factory=...)` with fakes: `FakeLLM`, `mock_search`, `FakeTools`, `MemorySaver`.
* **Test through the real HTTP surface**: sign up, create a conversation, stream a message, parse the SSE events, resume after an interrupt, assert outfits saved, assert **another user gets 404**, assert rate limits return 429 with `Retry-After`, assert audit entries exist and the chain verifies.
* **Security tests as first-class tests**: no token / garbage token → 401; refresh without CSRF header → 403; reuse of a refresh token revokes the family; weak passwords → 422; metrics endpoint off without a token; log lines contain no secrets.
* **Clock injection** for limits (`clock=` parameters) and token timing (`now=` parameters on minting functions).
* Keep tests **fast** (the whole API suite runs in seconds because the model and search are fake), and run the **live** path separately.

See Chapter 29 for the testing strategy as a whole.

## 18.9 Concurrency, workers and graceful operation

### Processes and workers

One `uvicorn` process runs one event loop and a thread pool. To use several CPU cores, run **multiple worker processes** (`uvicorn --workers N`, or gunicorn managing uvicorn workers) or **multiple containers** behind a load balancer. **Each process has its own memory**, which collides with this app's in-memory state: rate limiters, `active_conversations`, login-failure counters. With N workers each has separate counters (limits effectively multiply by N) and the "one turn at a time" lock stops protecting you. The docs say so ("with several copies of the API each has its own counters, so before scaling out these move to a shared store such as Redis"). Chapter 32 walks the migration.

### Graceful shutdown

Containers receive **SIGTERM** on stop/redeploy. uvicorn stops accepting new connections and lets in-flight requests finish (within a timeout), then runs the lifespan shutdown. For long streams (30-60 s turns), set orchestrator **termination grace periods** longer than your longest turn, or turns are cut mid-stream (the checkpoint keeps state, but the user sees an error). Keep health checks accurate: report "not ready" while draining.

### Timeouts and limits

Server keep-alive timeout, proxy timeouts (Caddy), client timeouts, **per-request deadline** you control (the agent has bounded steps but no global wall-clock cutoff: an honest improvement), maximum request body size, and maximum concurrent connections (`--limit-concurrency`) to shed load rather than collapse.

### Blocking and CPU work

* Never block the event loop: use `async` drivers/clients in `async def`, or `def` endpoints, or `run_in_threadpool`.
* **CPU-heavy** tasks (hashing, embeddings, image processing) belong in the thread pool for short bursts or in **separate worker processes/services** for heavy loads.
* Argon2 parameters are a *security-performance dial*: each login costs real CPU and memory; the login limiter protects you from being DoS'd by it.

## 18.10 Long-running and background work

Some work should not live inside a request:

* **FastAPI `BackgroundTasks`**: run after the response is sent, in the same process; fine for small fire-and-forget tasks; lost if the process dies.
* **Task queues** (Celery, RQ, Arq, Dramatiq, Temporal, cloud queues like SQS): durable jobs processed by separate workers, with retries, scheduling and visibility.
* **The job-table pattern**: write a `jobs` row (`pending`), a worker claims with `SELECT ... FOR UPDATE SKIP LOCKED`, runs, updates status/result; the client polls or receives an SSE event. *This is exactly how the blocked "try it on me" feature (image generation, tens of seconds, rate-limited provider) should be built*: a `generate_tryon` job plus status endpoint, never a request that waits.
* **Outbox pattern**: write the event and the state change in one transaction, then publish reliably.
* Make jobs **idempotent** and **retry-safe**.

## 18.11 A minimal service from scratch

```python
# app.py: run with:  uvicorn app:app --reload
import asyncio, json, time
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

app = FastAPI()

class Ask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)

def current_user(authorization: str = Header(default="")) -> str:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or token != "dev-token":      # replace with real verification
        raise HTTPException(401, "Please log in.", headers={"WWW-Authenticate": "Bearer"})
    return "user-1"

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/ask")
async def ask(body: Ask, user: str = Depends(current_user)):
    async def events():
        try:
            for stage in ("understood", "searching", "done"):
                await asyncio.sleep(0.5)                          # stand-in for real work
                yield f"event: status\ndata: {json.dumps({'stage': stage})}\n\n"
        finally:
            pass                                                  # release resources here
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

Try: `curl -N -H "Authorization: Bearer dev-token" -H "Content-Type: application/json" -d '{"text":"hi"}' localhost:8000/ask`. Then add: a settings class, a database pool via lifespan, a rate limiter dependency, request-id middleware, and a test using `TestClient`.

## 18.12 Choosing a framework

| Framework | Strengths | Trade-offs |
|---|---|---|
| **FastAPI** | async, type-driven validation, OpenAPI, great for AI/ML backends | younger ecosystem for admin/ORM; you assemble pieces |
| **Django (+DRF)** | batteries included: ORM, admin, auth, migrations | heavier; async story is newer |
| **Flask** | minimal, flexible | sync by default; you add validation/DI yourself |
| **Express / NestJS** (Node) | huge ecosystem; one language with the front end; NestJS adds structure | different AI ecosystem; typing discipline |
| **Spring Boot** (Java) / **ASP.NET Core** | enterprise standards, performance | verbosity, different talent pool |
| **Go (net/http, Gin, Fiber)** | performance, simple deploys | smaller AI library ecosystem |

For AI backends, **Python + FastAPI** is the pragmatic default because the model, retrieval and evaluation libraries live in Python.

## 18.13 An honest code review of `services/api`

Strengths: thin routes; plain-function domain logic; every query parameterised; uniform errors; layered limits; injected dependencies; consistent audit; metrics without user data; tests through the real HTTP surface.

Things a reviewer would raise (each is a good exercise, and a good interview answer about "what would you improve?"):

1. **Module-level `app = create_app(run_migrations=True)`** performs I/O on import; prefer `--factory` and an explicit migration job.
2. **In-memory state** (limiters, active set, replay guard, caches) prevents horizontal scaling (Redis).
3. **No global per-turn deadline**; add a wall-clock cap that cancels the graph stream.
4. **One DB role** with owner privileges.
5. **`events()` is a ~65-line closure** doing streaming, persistence, metrics and error handling: extract a service class to unit-test the turn logic without HTTP.
6. **`BUY_LINKS` metric never incremented** (Chapter 13).
7. **No CSP** header; no `Strict-Transport-Security` on the API itself (Caddy adds HSTS).
8. **Audit-log growth** has no retention/checkpoint strategy.
9. **Search worker threads lose the request-id context var** in log lines (Chapter 13).
10. **Chat history endpoint** rebuilds graph state on every GET (cheap now; cache if it grows).

## Common mistakes

* Blocking calls inside `async def`.
* Opening a DB connection per request instead of pooling; leaking connections.
* Business logic in route functions.
* Returning ORM/internal objects without `response_model`.
* Leaking exception text or distinguishing "no such user" from "wrong password".
* Trusting path ids without ownership checks.
* Doing validation after starting a stream.
* Using in-process state in a multi-worker deployment.
* Skipping graceful shutdown (cutting long streams on deploy).

## Summary

* ASGI + FastAPI: async-capable, type-driven; choose `async def` for awaiting I/O, `def` for blocking/CPU work (thread pool).
* Use an app factory, lifespan, routers, dependencies, and middleware; keep routes thin and logic in plain functions; inject collaborators.
* Validate at the edge with Pydantic; shape outputs with `response_model`; keep errors uniform and safe.
* Streaming needs correct headers, up-front validation, always-terminating events and `finally` cleanup.
* Concurrency lives in processes, threads and event loops; in-memory state limits scaling; plan graceful shutdown and timeouts.
* Test through the real HTTP layer with real Postgres and fake external services.

## Key terms

*ASGI, WSGI, uvicorn, Starlette, FastAPI, event loop, thread pool, lifespan, router, dependency injection, middleware, `response_model`, `StreamingResponse`, worker process, SIGTERM, graceful shutdown, `BackgroundTasks`, task queue, idempotency key.*

## Interview questions

1. What is the difference between `def` and `async def` endpoints in FastAPI? Which would you use for password hashing and why?
2. How does FastAPI's dependency injection work and why is it useful for auth and testing?
3. How do you stream a response and what can go wrong (buffering, disconnect, errors mid-stream)?
4. What problems appear when you run several uvicorn workers with in-memory rate limiters?
5. How would you design the API for a 60-second image-generation feature?
6. How do you prevent IDOR in an API?
7. What does a graceful shutdown look like for long-lived streams?
8. How would you test this API without a real model or search?

## Exercises

1. Build the minimal service in 18.11, then add JWT verification, a rate-limit dependency, and a database-backed `/me`.
2. Change `POST /conversations/{id}/messages` to enforce a wall-clock deadline (cancel after 90 s with an `error` event).
3. Run the API with `--workers 2` and demonstrate that the per-user chat limit is no longer exact; then design the Redis fix.
4. Write an ASGI middleware (not `BaseHTTPMiddleware`) that adds the request id header and compare behaviour with streaming.
5. Implement a job-table-based `/tryon` endpoint with a worker loop using `FOR UPDATE SKIP LOCKED`, polling status, and tests.
