# Appendix D. Honest Limitations and Roadmap

Knowing your system's limits is part of owning it. This appendix consolidates what the project does **not** do, the defects and sharp edges found while writing this book, the decisions made (and one reversed), and a prioritised roadmap. Items cross-reference the chapters that explain them.

---

## D.1 What is built and verified

LangGraph stylist agent with interrupts and Postgres checkpoints; rule-based verifier (men-only, assumed-colour fallback); private MCP tool server (search, buy link, SSRF-safe link check) with RS256 single-use tokens, host/origin guards, rate limits and credit caps; Postgres schema via numbered SQL migrations; hash-chained audit log; accounts (Argon2id, rotating refresh tokens with theft detection, lockouts); streaming chat API (SSE) and buy-link endpoint; Next.js UI; hardened Docker images and compose files (dev and prod layouts); Caddy as the single door; Prometheus/Grafana/Jaeger (local profile); Mastra evals (13 cases, 12 scorers, gates) with a second audit chain; ~224 Python tests plus TypeScript tests; browser end-to-end verification in Edge via Playwright during development.

## D.2 Not built (from the README and notes)

| Item | Status | Where covered |
|---|---|---|
| **"Try it on me"** (photo upload, character sheet, try-on images) | blocked on choosing an image provider (the proposed model name could not be verified) | 31 (Case 6), 32 |
| **Model-based or human taste judge** | not built (no LLM quota to build/test it) | 12 |
| **Real-model eval run** | limited by the free-tier quota (50 requests/day) | 12, 14 |
| **Log search (Loki)**, alerting | JSON logs only; no Alertmanager | 13, 28 |
| **Hosted deployment** | VM layout (`docker-compose.prod.yml`) and a Railway four-service layout (`apps/web/Dockerfile.railway`, `docs/deploy.md` section 3) are documented; confirm what is actually live before claiming it | 1b (1b.9), 27 |
| **External anchoring of audit hashes** | not done | 22 |
| **Mastra gateway** | skipped on purpose; UI talks to the API directly | 15 |
| **"Show more" / "make cheaper" follow-ups** | not built | 9, 32 |
| **CI pipeline** | none committed | 28 |
| **Backups** | none configured | 17, 27 |
| **Uncommitted work** | deployment files (Dockerfiles, prod compose, Caddy, scripts, docs) were uncommitted when this book was written; push only when you decide | 24 |
| **Keys that appeared in output/files** | should be rotated (OpenRouter, SerpAPI) | 20, 21 |

## D.3 Limitations of the current design

### Scaling and state
* Rate limiters, login lockout, the one-turn-per-conversation lock, the MCP replay guard, credit ledger and caches are **in-process memory** (Chapter 32). With more than one instance, limits multiply, replay is possible once per replica, credit caps weaken, and **buy-link lookups can fail** because `detail_refs` lives in the instance that did the search.
* Each chat turn occupies a worker thread for its whole duration (tens of seconds); per-process concurrency is bounded by the thread pool.
* The `SlidingWindow` keeps a key per distinct caller forever (slow memory growth); `TTLCache` evicts FIFO, not LRU.
* A global advisory lock serialises every audit append (throughput ceiling; fine at current scale).
* A new MCP client and event loop are created for each search (no connection reuse).

### Quality and data
* The verifier is **keyword-based**: colour words inside brand names (for example a brand containing "Red") can cause false rejections; synonyms outside the table can miss; gender from text is approximate.
* Colour is stated in only ~11% of titles; ~54% of results are usable via the assumed-colour fallback.
* The UI badge says "Colour not confirmed" for **any** low-confidence outfit, though low confidence can come from a partially matched item description; the evidence needed to be precise already exists in `verification.checks`.
* Search results link to Google Shopping pages; the real store link costs another credit and is fetched only on Buy.
* Demo-mode evals prove plumbing and guarantees, not real-model quality or taste.

### Security and privacy
* No MFA, email verification, password reset, breached-password check, session list, CAPTCHA.
* No CSP header; images load directly from retailer CDNs (IP exposure to third parties).
* The client navigates to the buy URL without re-validating the scheme (the server guarantees https and allow-listed domains).
* One database role owns tables and can drop audit triggers; the audit chain is unanchored.
* Conversation text lives in LangGraph checkpoint tables with no retention policy; account erasure does not cascade there, nor to the audit tags or backups.
* The free model provider may log or train on prompts.
* `FORWARDED_ALLOW_IPS="*"` is safe only because the API container is not published.
* `.env.production` concentrates every secret in one file; the dev compose publishes Postgres and the API; Grafana's admin password has a placeholder default.
* Refresh-token **two-tab race** can cause a false reuse detection and logout.
* Admin is determined by an email allow-list.

### Observability and operations
* `BUY_LINKS` counter is defined but never incremented; no token-usage or cost metrics; worker-thread log lines may lose the request id (context variables do not cross `ThreadPoolExecutor` threads).
* Tracing is client-driven (Mastra builds spans from `status` events); the API itself emits no OpenTelemetry spans.
* Mastra's libSQL store does not persist Mastra's own metrics/logs; tool-server panels are empty in demo mode; rate-limit waits show as unexplained gaps in traces.
* No external uptime/certificate monitoring; no alerts; no runbooks beyond the docs.
* No per-turn wall-clock deadline in `chat.send`.

### Code structure
* `app = create_app(run_migrations=True)` at import time performs I/O; prefer `--factory` and a separate migration job.
* `events()` in `routes/chat.py` is a long closure combining streaming, persistence, metrics and error handling; extract a service object for unit testing.
* Free-text outputs (`rationale`, style descriptions) are model-written and displayed as plain text; fine for safety, unverified for quality.

## D.4 Decisions recorded (ADR-style summaries)

| Decision | Why | Revisit when |
|---|---|---|
| Menswear only; never ask gender | product scope; simpler flow; verifier always checks "men" | broadening the audience |
| Tool-calling for structured output | the free model rejects `json_schema`, JSON mode returned nulls | switching models (re-test methods) |
| Skip the Mastra gateway; use Mastra for evals/tracing/audit | a gateway added a hop and boundary without solving a problem | multiple clients or a real BFF need |
| Private MCP server with signed single-use tokens | privilege boundary, replay protection, per-user limits | needing multiple replicas (shared replay store) or third-party clients (OAuth) |
| Fetch the real store link only on Buy | each lookup costs a credit | a catalogue/affiliate API with direct links |
| Assumed colour as low-confidence, shown to users | only ~11% of titles state colour | richer product data |
| Postgres checkpointer for agent state | durable pause/resume across restarts | scale or retention pressure (separate DB) |
| Plain SQL migrations at startup | transparency, simplicity | multiple instances (run as a release job) |
| One public door (Caddy), same origin | no CORS, cookies work, minimal surface | CDN/WAF in front, multi-service growth |
| Free model for development | zero cost | before real users (paid model) |
| Hash-chained audit + triggers (two layers) | detect and prevent | adding external anchoring and restricted DB roles |
| Demo mode refused in prod | prevent shipping the fake model | never |

## D.5 Prioritised roadmap

| Priority | Item | Chapter |
|---|---|---|
| **P0** | Backups with tested restore; rotate exposed keys; paid model with budget alerts; CI with tests, evals and scans; separate DB roles | 17, 20, 28 |
| **P1** | Per-turn deadline; token/cost metrics; alerts and uptime checks; fix `BUY_LINKS`; log shipping; CSP; account basics (verification, reset, MFA/SSO); account erasure incl. checkpoints; audit-head anchoring | 13, 21, 22 |
| **P1** | Redis for shared limiters, replay guard, credit ledger and caches; DB lease for the turn lock | 32 |
| **P2** | Two or three API instances behind Caddy; managed Postgres; retention for checkpoints; migrations as a release step | 32 |
| **P2** | Real-model eval suite, taste judge, production sampling, canary prompt/model rollout | 12, 28 |
| **P3** | LLM gateway and routing; search fallback or affiliate/catalogue integration; verifier improvements (brand-aware colour, structured attributes) | 31, 32, 11 |
| **P3** | Async jobs and image pipeline for try-on; async agent refactor; Kubernetes/IaC if scale or org demands | 31, 32, 26 |

## D.6 If I rebuilt it

* Start with the **canvas and eval dataset**, then the skeleton with fakes (as done), but put **CI and backups on day one**.
* Use a **shared-state-ready design from the start**: Postgres leases and Redis-compatible interfaces for limiters.
* Add **OpenTelemetry in the API** from the beginning, with trace ids already propagated.
* Keep **product data structured** (affiliate feeds) instead of parsing titles.
* Make **evidence visible in the UI** (name the unconfirmed attribute).
* Build the **taste judge and live eval budget** earlier, to measure quality, not only guarantees.

## D.7 How to use this appendix

In interviews, volunteer a limitation with its fix before you are asked; in customer work, turn this list into a risk register and a roadmap with owners and dates; in your own projects, write the equivalent file on day one and keep it current.
