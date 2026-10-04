# Chapter 1. The Project Tour

> **Learning objectives.** After this chapter you can (1) describe what AI Stylist does and draw its architecture from memory, (2) trace one user request through every component, (3) name the design principles behind the system and recognise them in code, and (4) say what is *not* built and why.
>
> **Prerequisites.** None. Every term used here is explained again in later chapters; treat this chapter as a map of a city you are about to study street by street.

---

## 1.1 The product

**AI Stylist** is a chat application for **menswear in India**. The shopper types something like *"College wear, around ₹4000"*. The system:

1. **Understands** the request, extracting two required facts: the **budget** (in rupees) and the **occasion**. If either is missing, it asks.
2. **Proposes five style directions** (streetwear, smart casual, minimalist, ...) and waits for the shopper to pick one (or describe their own).
3. **Plans four outfits.** Each outfit is exactly one top and one bottom, with colours, fit and a per-item price cap, written by a language model.
4. **Searches real stores** (Myntra, Amazon.in, Flipkart, AJIO, ...) for each item through a *private tool server*.
5. **Verifies every candidate product** with a rule-based checker: price, garment type, colour, men's-not-women's-or-kids', fit, fabric. Wrong products are dropped.
6. **Shows the outfits** with photos, prices and a **Buy** button. Clicking Buy asks the tool server for the store's own page, checks that the link is alive, and opens it.

Behind that simple flow sit user accounts, a database, a streaming API, rate limits, an append-only tamper-evident audit log, an evaluation harness, traces and dashboards, hardened containers, and a single public entrance with automatic HTTPS.

The product is **menswear only** by decision (recorded early in the project): the app never asks for gender, never takes a gender parameter, and the verifier always checks "men's".

## 1.2 The architecture in one picture

```
                                 ┌───────────────────────────────────────────────────────┐
                                 │                 Docker network (private)              │
                                 │                                                       │
 Browser ── HTTPS ──►  Caddy ────┼──► web   (Next.js, React UI)                          │
        (only public door)       │                                                       │
                          │      │                                                       │
                          └──────┼──► api   (FastAPI + LangGraph agent)                  │
                                 │       │         │                                     │
                                 │       │         └─► Postgres (users, conversations,   │
                                 │       │              outfits, audit log, agent state) │
                                 │       │                                               │
                                 │       └─► mcp   (private tool server, FastMCP)        │
                                 │              │                                        │
                                 └──────────────┼────────────────────────────────────────┘
                                                ▼
                                   SerpAPI (Google Shopping)  +  retailer pages (link checks)

 api ──► OpenRouter (the chat model, over the internet)

 Separate, local only:   apps/mastra  (evals, tracing, audit chain)  ──►  Jaeger, Prometheus, Grafana
```

### The components

| Component | Location | Language | Job |
|---|---|---|---|
| **Web app** | `apps/web` | TypeScript, Next.js 16, React 19 | The chat UI: login, conversation list, style cards, outfit cards, Buy buttons |
| **API** | `services/api` | Python 3.12, FastAPI | Accounts, sessions, rate limits, the streaming chat endpoint, buy-link endpoint, admin audit verification. Hosts the **LangGraph agent** |
| **Tool server (MCP)** | `services/mcp` | Python 3.12, FastMCP | The *only* component that talks to SerpAPI and retailer pages. Exposes tools `search_products`, `get_buy_link`, `check_link`, `ping` |
| **Database** | Docker `postgres:17` | SQL | Users, refresh tokens, conversations, outfits, the hash-chained audit log, **and** LangGraph's saved agent state |
| **Reverse proxy** | `infra/caddy/Caddyfile` | Caddy 2 | The only published ports (80/443); routes API paths to `api`, everything else to `web`; automatic HTTPS |
| **Evals app** | `apps/mastra` | TypeScript, Mastra | Plays 13 scripted shopper sessions, scores each with 12 scorers, keeps a second hash-chained audit trail |
| **Observability stack** | `docker compose --profile observability` | (images) | Jaeger (traces), Prometheus (metrics), Grafana (dashboards), all bound to `127.0.0.1` |
| **External: model** | OpenRouter | HTTP API | The language model (a free model during development) |
| **External: search** | SerpAPI | HTTP API | Google Shopping results |

### Why split it this way?

Each split exists for a reason you will meet again in every serious system:

* **The tool server is separate from the API** so that the component holding the outside-world powers (search key, URL fetching) can be locked down independently, has *no public address*, and can be reused by other agents. It is a **least-privilege** boundary.
* **The agent runs inside the API** (not as its own service) because it is the API's core logic; splitting it further would add network hops without a security or scaling benefit at this size.
* **The database holds everything stateful** so every other container can be thrown away and recreated without losing data. This is the **stateless services, stateful store** pattern.
* **Caddy is the single door** so there is exactly one place to enforce HTTPS, one set of routes, and one thing to firewall.
* **The evals app is separate** (TypeScript, local only) because it *tests* the running system from the outside, as a user would. It never shares code with the backend, so it cannot hide a bug that a real client would see.

## 1.3 One request, end to end

The best way to understand a system is to follow one request through it. We follow: *the shopper logs in, asks for college wear around ₹4000, picks a style, gets outfits, and clicks Buy on one item.*

### Step 0. Loading the page

The browser requests `/` from Caddy. Caddy matches the path against its API allow-list (`/auth/*`, `/conversations`, `/conversations/*`, `/products/*`, `/admin/*`, `/health`). `/` is not on it, so Caddy forwards to the **web** container (Next.js), which returns the React app.

### Step 1. Logging in

The React app calls `refreshSession()` (`apps/web/lib/api.ts`), which sends `POST /auth/refresh` with credentials. The browser automatically attaches the **refresh-token cookie** if one exists (it is `HttpOnly`, so JavaScript cannot read it, and `SameSite=Strict`, `Path=/auth`, so it is sent only to `/auth/*` from the same site). With no cookie the server answers 401 and the UI goes to `/login`.

On the login form the shopper submits email and password. `POST /auth/login` runs:

1. a per-IP rate limit (30 auth calls a minute);
2. a **lockout** check: five wrong passwords for one *email+IP pair* within 15 minutes locks that pair out;
3. `accounts.authenticate`: look up the user by lowercase email, verify the password against the stored **Argon2id** hash. If the email does not exist, it *still* verifies against a dummy hash, so "no such user" takes as long as "wrong password" (no timing leak);
4. on success, a new **refresh token family** is started (a 48-byte random secret, only its SHA-256 hash stored in the database), an **audit-log** row is appended, and the response sets the refresh cookie and returns a 15-minute **access token**, a JWT signed with the API's *private* RSA key.

The browser keeps the access token **in memory only** (a module variable), never in `localStorage`.

### Step 2. Creating a conversation and sending the first message

The shopper types *"College wear, around ₹4000"*. The UI calls `POST /conversations` (creates a row, enforces a cap of 30 new conversations a day), then `POST /conversations/{id}/messages` with the text.

`routes/chat.py::send` does the following before streaming anything:

* verifies the access token (RS256, pinned algorithm, issuer, audience, expiry);
* checks the conversation **belongs to this user** (someone else's id looks like "not found");
* applies a per-user chat rate limit (10 messages a minute);
* takes an in-process lock so only **one turn at a time** runs per conversation (a second returns 409);
* asks LangGraph for the conversation's saved state to see whether the graph is **paused waiting for an answer** (a pending *interrupt*);
* appends an audit entry recording *that* a message was sent (its length, never its text).

Then it returns a `StreamingResponse` of **server-sent events (SSE)**. The response starts immediately and keeps sending events as the agent works.

### Step 3. The agent runs (LangGraph)

The graph (`agent/graph.py`) is a small state machine:

```
START → gather_prefs ──(missing something?)──► ask_user ─┐ (pauses; resumes with the answer)
              ▲                                          │
              └──────────────────────────────────────────┘
              │ (have budget + occasion)
              ▼
        propose_styles → wait_for_choice (pauses) → plan_outfits → find_products
                                                         ▲               │
                                                         │               ▼
                                                         └── (too few) rank_and_validate ── respond → END
```

For our message:

1. **`gather_prefs`**: one LLM call using *structured output* (a Pydantic schema `PrefsExtraction`) to pull `budget_inr = 4000` and `occasion = "college"` from the conversation. Nothing is missing, so the graph moves on.
2. **`propose_styles`**: a second LLM call returns five `StyleOption`s. The graph then hits `interrupt({"type": "choose_style", ...})` inside `wait_for_choice` and **pauses**. Its full state is saved to Postgres by the checkpointer. The SSE stream sends an `interrupt` event and a `done` event. The HTTP request ends, and nothing is running on the server for this conversation.
3. The UI shows five **style cards**. The shopper clicks "Smart Casual". The UI sends `POST .../messages` with the style id. This time the API sees a pending interrupt and resumes the graph with `Command(resume="smart-casual")`. The graph **continues from where it paused**, possibly hours later or after a server restart.
4. **`plan_outfits`**: a third LLM call (prompt `plan_outfits.v2.md`) returns four `OutfitSpec`s: for each, a top and a bottom with item, colour, fit, and a max price. Code then **clamps** each outfit's prices to the budget (the model is *told* the budget; the code *enforces* it).
5. **`find_products`**: for all 8 items, searches run **in parallel** (a thread pool), each calling `search_products` on the MCP tool server. A user-signed token accompanies every HTTP request (Step 4 below).
6. **Verification**: every returned product is checked by `verify.py` against the spec (price, item words, colour, men's, fit, fabric). The best verified product per slot is chosen (confirmed attributes first, then match score, then price under the cap). An outfit exists only if both items verified and the sum is within budget.
7. **`rank_and_validate`**: a second line of defence re-checks totals and verification flags; confirmed outfits sort first. If fewer than four survive, the graph loops back to `plan_outfits` with **notes** explaining which items failed ("no verified match for 'peach chinos'"), up to a retry limit. If search itself was unavailable, it stops instead of burning more model calls.
8. **`respond`**: a plain summary message. The API saves the outfits (`outfits`, `outfit_items` tables), appends an `outfits_delivered` audit entry, and streams `outfits`, `message` and `done` events.

A normal conversation uses about **3 to 6 model calls** and **8 searches per planning round**.

### Step 4. Inside one tool call

When `McpProductSearch` calls `search_products`, a FastMCP client sends HTTP requests to `http://mcp:8001/mcp`. For **every HTTP request**, `ServiceTokenAuth` mints a brand-new JWT: `sub` = the user's id, `exp` = 30 seconds, a unique `jti`, signed RS256 with the API's *private* key.

The tool server:

1. checks the `Host` header is `mcp` (a DNS-rebinding defence) and any `Origin` is acceptable;
2. verifies the token with its *public* key (it can verify tokens but never create them), enforces a 60-second maximum lifetime, and records the `jti` so **a second use of the same token is refused** (replay protection);
3. checks the user's **rate limit** (60 calls a minute);
4. on a cache miss, spends one **search credit** against per-user and global daily caps, then calls SerpAPI Google Shopping with `men <colour> <fit> <fabric> <item>` and `gl=in`;
5. parses the response into typed `ProductResult`s, drops stores not on the retailer allow-list and items over the price cap, and returns them.

Nothing here is trusted: the API cannot be tricked into bypassing the tool server, and the tool server cannot be reached by anyone who does not hold a fresh signature.

### Step 5. Clicking Buy

Search results link to a *Google Shopping page*, not the store. So the Buy button calls `POST /products/{product_id}/buy-link`:

1. the API checks that product id belongs to an outfit **shown to this user** (so nobody can spend search credits on arbitrary ids);
2. rate-limits (10 per minute per user);
3. calls `get_buy_link` (1 credit) to learn the store's own product page, then `check_link` to see if the page is alive, using strict **SSRF protection** (https only, allow-listed store domains only, public IP addresses only, connect to the *checked* IP address, re-check at every redirect);
4. appends a `buy_link_opened` audit entry;
5. returns the URL. The browser (which opened a blank tab *synchronously inside the click* so pop-up blockers allow it) navigates that tab to the store.

### What gets recorded along the way

* **Postgres audit log**: register/login/failed login, message sent (length only), outfits delivered, buy link opened. Hash-chained.
* **JSON logs**: one object per line with `request_id` and `trace_id`.
* **Prometheus metrics** on API and tool server: counts and timings, never user data.
* **Traces**: when the Mastra eval harness drives the system, it sends a W3C `traceparent` header and the API adopts that trace id.

## 1.4 The design principles (learn these; they transfer)

These are the ideas behind a hundred small decisions in the repo. Each is a theme of this book.

1. **The model proposes, code disposes.** The LLM decides *what to look for*. Deterministic code decides *what is true*: the budget is clamped in code, every product is verified by rules, outfits are re-validated before being shown. Language models are creative but unreliable; never let them be the last line of defence. (Chapter 11)
2. **Least privilege.** Every component holds only the power it needs. The tool server has the public key only (it can check signatures, never mint them); the API has the private keys; containers run as non-root with all Linux capabilities dropped. (Chapters 20, 25)
3. **Defence in depth.** No single control is trusted. The tool server is protected by (a) no public address, (b) signed tokens, (c) single-use tokens, (d) host/origin checks, (e) rate limits and credit caps. Any one can fail. (Chapter 21)
4. **Fail closed.** The tool server **refuses to start** without a valid public key. Demo mode **refuses to run** in production. The replay guard **refuses** a token when its memory is full rather than forgetting. When unsure, deny.
5. **Honest uncertainty.** A product whose colour the page did not state is not "a match", it is `assumed`, flagged `confidence: low`, ranked below confirmed ones, and *shown to the user as "Colour not confirmed"*. A link that cannot be checked is `unverified`, not `dead`. Never turn "I do not know" into "yes" or "no".
6. **One seam per outside service.** SerpAPI's response shape is known to exactly one file (`providers/serpapi.py`). The chat model is behind one function (`get_llm`). Swap providers by writing one adapter, not by editing the agent.
7. **Thin wrappers, real logic in plain functions.** The MCP tool decorators in `server.py` are thin; the logic lives in `tools/*.py` with no framework code, so tests need no network. (Chapter 29)
8. **Observable by default.** Traces, metrics and logs carry only names and numbers, and tests check that no user data leaks into them. (Chapter 13)
9. **State belongs in a database, not in the process.** The conversation survives restarts because LangGraph checkpoints into Postgres. (The few in-memory structures, such as rate limiters, are flagged honestly as limits.) (Chapter 30)
10. **Secrets never travel in images or git.** `.env` is git-ignored, images contain code only, a test fails if a real-looking secret appears in `.env.example`. (Chapters 21, 25)
11. **Make the cheap failure loud and the expensive one impossible.** A wrong colour is caught by a rule (cheap, loud); spending unbounded search credits is impossible because caps exist (expensive, prevented).
12. **Write for the next reader.** Tool descriptions, schema field descriptions, error messages and comments are written for the *consumer* (a model, a client, a future engineer).

## 1.5 The repository map

```
.
├── apps/
│   ├── web/                 Next.js UI (login, chat, outfit cards)
│   └── mastra/              evals, tracing, audit chain (TypeScript)
├── services/
│   ├── api/                 FastAPI + LangGraph agent
│   │   ├── src/api/
│   │   │   ├── main.py         builds the app: middleware, routes, lifespan
│   │   │   ├── config.py       all settings (environment variables)
│   │   │   ├── db.py           connection pool + migration runner
│   │   │   ├── repo.py         every SQL query for chat features
│   │   │   ├── accounts.py     register, login, refresh rotation
│   │   │   ├── audit.py        the hash-chained audit log
│   │   │   ├── mcp_auth.py     mints single-use tokens for the tool server
│   │   │   ├── telemetry.py    metrics, JSON logs, trace ids
│   │   │   ├── agent/          graph.py, state.py, schemas.py, verify.py, find.py, llm.py, mcp_search.py, demo.py, prompts.py
│   │   │   ├── routes/         auth.py, chat.py, products.py, admin.py
│   │   │   └── security/       passwords.py, tokens.py, throttle.py
│   │   ├── migrations/001_init.sql
│   │   └── tests/              ~146 test functions (real throwaway Postgres)
│   └── mcp/                 the private tool server
│       └── src/mcp_server/  server.py, auth.py, limits.py, cache.py, net.py, metrics.py, schemas.py,
│                            tools/ (search_products, buy_link, check_link), providers/serpapi.py
├── prompts/stylist/         versioned prompts (extract_prefs.v1, propose_styles.v1, plan_outfits.v1/v2)
├── infra/
│   ├── caddy/Caddyfile      the one public door
│   └── observability/       prometheus.yml, Grafana provisioning + dashboard
├── scripts/                 generate_jwt_keys.py, init_production_env.py, init_observability.py
├── docs/                    mcp-guide.md, observability.md, deploy.md, tools-reference.html, and this textbook
├── docker-compose.yml       local/dev stack (+ optional observability profile)
├── docker-compose.prod.yml  hosted layout: only Caddy publishes ports
└── .env.example             every setting, documented, with no real secrets
```

(About 224 Python test functions in total: ~146 in the API, ~78 in the tool server, plus TypeScript tests for the web stream parser and the Mastra scorers/audit chain.)

## 1.6 The technology stack, and why each choice

| Layer | Choice | Why | Realistic alternatives |
|---|---|---|---|
| Language (backend) | Python 3.12 | The AI ecosystem lives in Python; type hints + Pydantic give safety | TypeScript/Node, Go, Java |
| Web framework | FastAPI | async, automatic validation from type hints, automatic docs, streaming | Django, Flask, Express/NestJS |
| Agent framework | LangGraph | explicit state machine, checkpointing, human-in-the-loop interrupts | plain code, LlamaIndex Workflows, OpenAI Agents SDK, Mastra, CrewAI |
| Model access | `langchain-openai` `ChatOpenAI` against OpenRouter | OpenRouter is OpenAI-compatible and fronts many models | direct vendor SDKs (Anthropic, OpenAI, Google) |
| Tool protocol | MCP via FastMCP | a standard for exposing tools; schema-validated; reusable | plain function calls, OpenAPI tools, gRPC |
| Search | SerpAPI Google Shopping | no scraping needed; structured results | store APIs, scraping, product feeds |
| Database | PostgreSQL 17 | relational integrity, JSONB, advisory locks, triggers, LangGraph checkpointer support | MySQL, SQLite (dev), DynamoDB |
| DB driver | psycopg 3 + `psycopg_pool` | modern, supports pooling and server-side features | SQLAlchemy, asyncpg |
| Tokens | PyJWT (RS256) | asymmetric signatures let the verifier be unable to forge | HS256, PASETO, opaque sessions |
| Passwords | argon2-cffi (Argon2id) | memory-hard, current best practice | bcrypt, scrypt |
| Frontend | Next.js 16, React 19, TypeScript | industry default; App Router | Vite + React, SvelteKit, Vue/Nuxt |
| Streaming | SSE over `fetch` | one-way server push; simple; works through proxies | WebSockets, long polling |
| Proxy | Caddy 2 | automatic HTTPS with almost no config | nginx, Traefik, cloud load balancers |
| Packaging | Docker multi-stage, non-root | reproducible, small, safer | Nix, buildpacks |
| Package mgmt | `uv` (Python), npm workspaces | fast, lockfiles | pip/poetry, pnpm/yarn |
| Observability | Prometheus + Grafana + Jaeger | industry standard, open source | Datadog, Honeycomb, Grafana Cloud, Langfuse/LangSmith for LLM tracing |
| Evals | Mastra scorers + own harness | TypeScript workflow engine with scorer abstractions | pytest + custom, promptfoo, Braintrust, Langfuse evals |

## 1.7 What was built, in the order it was built

Understanding the *sequence* teaches you how real projects grow safely:

1. **A walking skeleton**: an agent with a mock search and a mock model. Prove the flow first, with fake edges.
2. **The verifier**: deterministic checking of products against the request, with evidence recorded per attribute.
3. **The tool server**: MCP with `search_products`, then `get_buy_link` and `check_link`; schemas, caching, retries, tests against real saved SerpAPI responses (no network in tests).
4. **Locking the tool server down**: signed short-lived tokens, then single-use tokens, host/origin checks, rate limits, credit caps.
5. **Persistence and accounts**: Postgres schema as plain migrations, Argon2id, refresh-token rotation with theft detection, the audit log.
6. **Streaming API + UI**: SSE, ownership checks, the Next.js app, Playwright browser testing.
7. **Observability and evals**: metrics, JSON logs, trace-id propagation, Mastra workflow with 12 scorers, a second audit chain, Grafana dashboard.
8. **Deployment**: Dockerfiles, hardened containers, Caddy, `docker-compose.prod.yml`, deployment docs.

The order is the lesson: **make it work with fakes, make it correct, make it safe, make it persistent, make it visible, then ship it.**

## 1.8 Decisions the project made (and one it reversed)

* **Mastra as a gateway: skipped.** The original plan put a Mastra (TypeScript) gateway between the UI and the API. It was dropped: the UI talks to the API directly. Mastra became the **evals/tracing/audit** app. *Lesson:* a layer must earn its place; every hop adds latency, failure modes and security surface.
* **Free chat model.** `apodex/apodex-1.1-mini:free` on OpenRouter: structured output works via **tool calling**, not `json_schema` (the model rejects it) and not plain JSON mode (it returned nulls). The free tier allows 20 requests/minute and 50 requests/day, which is about eight conversations a day. *Lesson:* a vendor's *quota and feature support* are architecture constraints, discovered by testing, not by reading marketing pages.
* **Search results link to Google, not to the store.** SerpAPI shopping results carry a Google Shopping URL. Getting the real store page costs another credit, so it happens **only when the user clicks Buy**. *Lesson:* design the cost model into the flow.
* **Colour is stated in only about 11% of titles.** An "assumed colour" fallback raises usable results to about 54%, with honesty about confidence. *Lesson:* measure your data before designing the rules around it.
* **"Try it on me" (virtual try-on images): not built.** Blocked on choosing an image provider; the model name in the notes could not be verified. *Lesson:* do not build on a vendor claim you have not tested.

## 1.9 What is **not** built (the honest list)

This list is part of the project. Chapter 32 and Appendix D discuss how to close each gap.

* **Rate limiters, the token-replay memory, the search cache and the "one turn at a time" lock are in process memory.** Fine for one copy of each service; with several copies they need a shared store such as **Redis**.
* **No database backups** are configured; the data lives in one Docker volume on one machine.
* **No model-based or human judge of *taste***: the evals check guarantees (budget, verification, men's-only, no duplicates), not whether an outfit looks good.
* **No log search** (Loki/ELK); logs are JSON lines in container output.
* **No CI pipeline** is committed yet (Chapter 28 writes one).
* **External anchoring of audit hashes** is not done (so a database owner with full control could rewrite the whole chain consistently).
* **Not committed**: the deployment work (Dockerfiles, compose.prod, Caddy) was uncommitted at the time of writing; commit and push happen only when you ask.
* **The free model's quota** means real-model evals are limited until a paid model is chosen.

## 1.10 How to use the rest of the book

Whenever a chapter says **"In this project"**, open the named file and read it. After finishing Part III, return to Section 1.3 and reread it: every step will now be something you could implement yourself, explain to a customer, and defend in an interview.

## Summary

* AI Stylist = Next.js UI + FastAPI/LangGraph API + a private MCP tool server + Postgres, behind Caddy, observed by Prometheus/Grafana/Jaeger and tested by a Mastra eval harness.
* The agent is a **state machine** whose state is saved in Postgres, so it can **pause for the user and resume later**.
* The model *proposes*; deterministic code *verifies and enforces*.
* Security is layered: no public address, signed single-use tokens, rate limits and credit caps, SSRF protection, hardened containers, hash-chained audit.
* The project grew by making it **work with fakes, correct, safe, persistent, visible, then deployed**.

## Key terms

*agent, checkpointer, interrupt, SSE, MCP, JWT, RS256, refresh token rotation, Argon2id, SSRF, DNS rebinding, replay protection, least privilege, defence in depth, fail closed, hash chain, reverse proxy, structured output, verifier, demo mode.*

## Interview questions

1. Walk me through what happens, end to end, when a user sends a message in this app.
2. Why is the tool server a separate service with no public address? What is the cost of that split?
3. Why does the agent pause with `interrupt` rather than keep a request open waiting for the user?
4. Name three places where the code does *not* trust the language model, and why.
5. What are the three biggest scaling limitations of the current design?

## Exercises

1. Without looking, redraw the architecture diagram and label which component holds which secrets (private keys, public keys, search key, model key, database password).
2. Open `services/api/src/api/agent/graph.py` and list every place where a model call happens. Count the model calls for a conversation with a complete request and no replan.
3. Follow `buy_link` in `routes/products.py` and write the list of five checks it performs before opening the store link.
