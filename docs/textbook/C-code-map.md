# Appendix C. Code Map: File to Concept

Open each file with the matching chapter beside it. Paths are relative links from this document.

---

## C.1 API service: `services/api`

| File | What it contains | Concepts | Chapter |
|---|---|---|---|
| [src/api/main.py](../../services/api/src/api/main.py) | `create_app` factory, lifespan, middleware (ids, metrics, headers), `/health`, `/metrics`, router wiring, `DemoTools`, `make_graph_factory` | factories, DI, lifespan, middleware, security headers, demo vs live | 2, 13, 18 |
| [src/api/config.py](../../services/api/src/api/config.py) | `Settings` (pydantic-settings), `.env` discovery by walking parents | twelve-factor config, secure defaults | 2, 1b |
| [src/api/db.py](../../services/api/src/api/db.py) | pool factory, migration runner with advisory lock | pools, migrations, locks | 17 |
| [src/api/deps.py](../../services/api/src/api/deps.py) | `current_user`, `enforce` (429), `client_ip`, `sse()` | dependencies, uniform 401, SSE framing | 16, 18 |
| [src/api/repo.py](../../services/api/src/api/repo.py) | every chat SQL query | parameterised SQL, ownership scoping, joins vs N+1 | 17, 21 |
| [src/api/accounts.py](../../services/api/src/api/accounts.py) | register, authenticate, token family, `rotate`, logout | Argon2, rotation, reuse detection, savepoints, `FOR UPDATE` | 17, 20 |
| [src/api/audit.py](../../services/api/src/api/audit.py) | hash-chained append and `verify_chain` | hash chain, canonical JSON, advisory lock | 22 |
| [src/api/mcp_auth.py](../../services/api/src/api/mcp_auth.py) | `mint_service_token`, `ServiceTokenAuth` (per-request token) | JWT, RS256, single-use tokens | 8, 20 |
| [src/api/telemetry.py](../../services/api/src/api/telemetry.py) | trace-id parsing, `RunStats`, instrumented LLM/search, Prometheus metrics, JSON logging | observability | 13 |
| [src/api/security/passwords.py](../../services/api/src/api/security/passwords.py) | Argon2id hashing, policy, dummy-hash timing | password security | 20 |
| [src/api/security/tokens.py](../../services/api/src/api/security/tokens.py) | access JWTs, refresh token generation/hash | JWT, entropy | 20 |
| [src/api/security/throttle.py](../../services/api/src/api/security/throttle.py) | `SlidingWindow`, `FailureCounter` | rate limiting, deque | 3, 30, 32 |
| [src/api/routes/auth.py](../../services/api/src/api/routes/auth.py) | register/login/refresh/logout/me, cookie, CSRF header | session design | 16, 18, 20 |
| [src/api/routes/chat.py](../../services/api/src/api/routes/chat.py) | conversations, streaming `send`, interrupt handling, persistence, friendly errors | SSE, LangGraph driving, locks | 9, 16, 18 |
| [src/api/routes/products.py](../../services/api/src/api/routes/products.py) | buy-link flow (ownership, limit, tools, audit) | IDOR defence, tool client use | 8, 21 |
| [src/api/routes/admin.py](../../services/api/src/api/routes/admin.py) | admin audit verification (404 for others) | authorisation, existence hiding | 21, 22 |
| [src/api/agent/graph.py](../../services/api/src/api/agent/graph.py) | the LangGraph: nodes, edges, `clamp_to_budget`, `structured()` retry | agents, state, interrupts, bounds | 7, 9 |
| [src/api/agent/state.py](../../services/api/src/api/agent/state.py) | `StylistState` TypedDict + `add_messages` reducer | state, reducers | 9 |
| [src/api/agent/schemas.py](../../services/api/src/api/agent/schemas.py) | Pydantic models for prefs, styles, specs, products, reports | validation, validators, Literal | 2, 7, 11 |
| [src/api/agent/verify.py](../../services/api/src/api/agent/verify.py) | deterministic product verifier | three-valued logic, evidence | 11 |
| [src/api/agent/find.py](../../services/api/src/api/agent/find.py) | parallel search + verification + selection | thread pool, greedy selection, failure isolation | 4, 11 |
| [src/api/agent/mcp_search.py](../../services/api/src/api/agent/mcp_search.py) | MCP client wrapper, error mapping, sync/async bridge | tool client, retries | 2, 8 |
| [src/api/agent/llm.py](../../services/api/src/api/agent/llm.py) | `get_llm` for OpenRouter/OpenCode, IPv4 pinning | model gateway seam | 6, 15 |
| [src/api/agent/products.py](../../services/api/src/api/agent/products.py) | `ProductSearch` seam, `mock_search` with decoy | seams, test data | 11, 29 |
| [src/api/agent/demo.py](../../services/api/src/api/agent/demo.py) | `ScriptedLLM`, budget/occasion parsing | fakes, demo mode | 12, 29 |
| [src/api/agent/prompts.py](../../services/api/src/api/agent/prompts.py) | versioned prompt loader | prompt management | 7 |
| [migrations/001_init.sql](../../services/api/migrations/001_init.sql) | schema, constraints, indexes, append-only triggers | data modelling | 17 |
| [tests/](../../services/api/tests) | ~146 tests (real throwaway Postgres) | testing strategy | 29 |
| [Dockerfile](../../services/api/Dockerfile) | two-stage uv build, non-root, healthcheck | Docker | 25 |

## C.2 Tool server: `services/mcp`

| File | What | Concepts | Chapter |
|---|---|---|---|
| [src/mcp_server/server.py](../../services/mcp/src/mcp_server/server.py) | `build_server`, three tools + ping, throttling, `LimitedProvider`, `/metrics`, `/health`, bind guard | MCP, thin wrappers, limits | 8 |
| [auth.py](../../services/mcp/src/mcp_server/auth.py) | `ServiceJWTVerifier`, `ReplayGuard` | JWT verification, replay protection | 20 |
| [limits.py](../../services/mcp/src/mcp_server/limits.py) | `RateLimiter`, `CreditLedger` | rate limits, caps | 14, 30 |
| [cache.py](../../services/mcp/src/mcp_server/cache.py) | `TTLCache` | caching, eviction | 3, 30 |
| [net.py](../../services/mcp/src/mcp_server/net.py) | outbound HTTP, retries with backoff/jitter | reliability | 4, 11 |
| [metrics.py](../../services/mcp/src/mcp_server/metrics.py) | Prometheus counters, `tracked()` | observability | 13 |
| [schemas.py](../../services/mcp/src/mcp_server/schemas.py) | tool input/output models, `schema_version` | contracts | 8 |
| [config.py](../../services/mcp/src/mcp_server/config.py) | settings, retailer/domain allow-lists | config, allow-lists | 2, 21 |
| [tools/search_products.py](../../services/mcp/src/mcp_server/tools/search_products.py) | query building, cache, filtering | tool logic, retrieval | 8, 10 |
| [tools/buy_link.py](../../services/mcp/src/mcp_server/tools/buy_link.py) | store-page resolution | adapters, HTTPS upgrade | 8 |
| [tools/check_link.py](../../services/mcp/src/mcp_server/tools/check_link.py) | SSRF-safe link checker | SSRF, DNS rebinding | 21 |
| [providers/serpapi.py](../../services/mcp/src/mcp_server/providers/serpapi.py) | the only SerpAPI-aware code | adapter pattern | 15 |
| [tests/](../../services/mcp/tests) | ~78 tests, real saved responses | fixtures, contract tests | 29 |
| [Dockerfile](../../services/mcp/Dockerfile) | non-root, healthcheck | Docker | 25 |

## C.3 Web app: `apps/web`

| File | What | Concepts | Chapter |
|---|---|---|---|
| [lib/api.ts](../../apps/web/lib/api.ts) | token in memory, single-flight refresh, retry on 401, `ApiError` | session handling | 19, 20 |
| [lib/sse.ts](../../apps/web/lib/sse.ts) + [sse.test.ts](../../apps/web/lib/sse.test.ts) | robust SSE stream parser and tests | streaming, buffering | 2, 16, 19 |
| [lib/types.ts](../../apps/web/lib/types.ts) | API contract types (discriminated unions) | TypeScript | 19 |
| [components/Chat.tsx](../../apps/web/components/Chat.tsx) | conversation state machine | React state/effects | 19 |
| [components/OutfitCard.tsx](../../apps/web/components/OutfitCard.tsx) | Buy flow, tab-opening trick, notes | UX, security | 19 |
| [components/StyleCards.tsx](../../apps/web/components/StyleCards.tsx) | style choice UI | components | 19 |
| [app/login/page.tsx](../../apps/web/app/login/page.tsx), [app/page.tsx](../../apps/web/app/page.tsx), [app/layout.tsx](../../apps/web/app/layout.tsx) | routes and shell | Next.js App Router | 19 |
| [Dockerfile](../../apps/web/Dockerfile) | multi-stage Next build, `NEXT_PUBLIC_API_URL` | Docker, build-time env | 25 |

## C.4 Evals app: `apps/mastra`

| File | What | Chapter |
|---|---|---|
| [src/evals/cases.ts](../../apps/mastra/src/evals/cases.ts) | 13-case dataset | 12 |
| [src/evals/run.ts](../../apps/mastra/src/evals/run.ts), [report.ts](../../apps/mastra/src/evals/report.ts) | runner, gates vs soft signals, exit codes | 12 |
| [src/mastra/stylist/session.ts](../../apps/mastra/src/mastra/stylist/session.ts), [client.ts](../../apps/mastra/src/mastra/stylist/client.ts), [sse.ts](../../apps/mastra/src/mastra/stylist/sse.ts) | simulated shopper, API client with 429 retry | 12 |
| [src/mastra/scorers/rules.ts](../../apps/mastra/src/mastra/scorers/rules.ts), [index.ts](../../apps/mastra/src/mastra/scorers/index.ts) | 12 scorers, Mastra wrappers | 12 |
| [src/mastra/workflows/stylist-session.ts](../../apps/mastra/src/mastra/workflows/stylist-session.ts) | traced workflow, back-dated child spans | 12, 13 |
| [src/mastra/audit/chain.ts](../../apps/mastra/src/mastra/audit/chain.ts), [exporter.ts](../../apps/mastra/src/mastra/audit/exporter.ts) | hash-chained audit in libSQL, tracing exporter | 22 |
| [src/mastra/index.ts](../../apps/mastra/src/mastra/index.ts), [config.ts](../../apps/mastra/src/mastra/config.ts) | Mastra instance, allow-listed env loading | 15, 1b |

## C.5 Prompts, infra, scripts, docs

| Path | What | Chapter |
|---|---|---|
| [prompts/stylist/](../../prompts/stylist) | `extract_prefs.v1`, `propose_styles.v1`, `plan_outfits.v1/v2` | 7 |
| [docker-compose.yml](../../docker-compose.yml) | dev stack + observability profile | 26, 1b |
| [docker-compose.prod.yml](../../docker-compose.prod.yml) | hosted layout, one public door | 26, 27, 1b |
| [infra/caddy/Caddyfile](../../infra/caddy/Caddyfile) | reverse proxy and routing allow-list | 27 |
| [infra/observability/](../../infra/observability) | Prometheus config, Grafana provisioning and dashboard | 13 |
| [scripts/generate_jwt_keys.py](../../scripts/generate_jwt_keys.py) | RSA key pairs into env files, fingerprints only | 20, 1b |
| [scripts/init_production_env.py](../../scripts/init_production_env.py) | builds `.env.production` without printing secrets | 1b, 27 |
| [scripts/init_observability.py](../../scripts/init_observability.py) | metrics token for Prometheus | 13, 20 |
| [.env.example](../../.env.example) | every setting, no secrets | 1b, B.1 |
| [docs/mcp-guide.md](../mcp-guide.md), [observability.md](../observability.md), [deploy.md](../deploy.md) | project docs this book builds on | 8, 13, 27 |
| [README.md](../../README.md) | overview, security table, run instructions | 1 |

## C.6 Reading order for the code (a 3-hour code tour)

1. `README.md`, then `docker-compose.prod.yml` and `Caddyfile` (the shape of the system).
2. `routes/chat.py` + `agent/graph.py` (the heart: HTTP ↔ graph).
3. `agent/schemas.py`, `agent/verify.py`, `agent/find.py` (correctness).
4. `mcp_server/server.py`, `auth.py`, `tools/check_link.py` (the private tool server).
5. `accounts.py`, `security/*`, `routes/auth.py` (identity).
6. `audit.py`, `001_init.sql` (data and integrity).
7. `lib/api.ts`, `components/Chat.tsx` (the client).
8. `apps/mastra/src/evals/*` (how it is measured).
9. The tests next to each file you read.
