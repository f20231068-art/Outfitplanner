# Chapter 32. Scaling This App, Step by Step

> **Learning objectives.** Take the current single-node design and evolve it through a sequence of safe, justified stages: harden one node, move in-process state to shared stores, run several API instances, scale the database, build a model/tool gateway, add async jobs, and add redundancy; produce capacity numbers at each step; and present a prioritised backlog with reasons. This chapter is the "what would you do next?" interview answer, in detail.
>
> **Prerequisites.** Chapters 5, 17, 18, 26, 28, 30, 31.

---

> **Read first:** [Chapter 1b](01b-how-the-servers-connect.md) describes the five servers, how they are connected, and where each environment variable goes. This chapter assumes that wiring and shows how it changes at each scaling stage (for example, new servers such as Redis follow the recipe in section 1b.7).

> **Default answer to "What happens when traffic increases 100x?"** Start from a baseline (about 9 concurrent heavy turns and ~32,000 search credits a day at 50,000 monthly users) and convert to rates: at 100x that is roughly **840 concurrent turns, ~3 million search credits a day, ~150 model calls/s at peak, hundreds of DB writes/s, ~300 GB/month of checkpoints**. What breaks first, in order: (1) **cost** (search and model spend, before CPU), (2) **correctness of in-process limits, locks and caches** once there is more than one instance (including buy-link lookups), (3) **provider rate limits and tail latency**, (4) **thread-per-turn concurrency**, (5) **Postgres connections, the audit log's global lock and checkpoint growth**, (6) **single-VM redundancy**, (7) ops/observability, (8) abuse. Actions differ at 2x (harden), 10x (Redis, a few instances, managed DB) and 100x (async/autoscale, a different data source, partitioned storage, multi-AZ, bot defence), and each step is confirmed with a demo-mode load test. Full table and a 90-second answer: [Chapter 37, section 37.3](37-the-four-questions.md#373-what-happens-when-traffic-increases-100x).

## 32.0 Principles for scaling an existing system

1. **Measure first.** The real bottleneck is rarely where you guess. This app's first limits are an *external quota* and *in-process state*, not CPU.
2. **Fix correctness limits before capacity limits.** In-memory limiters and locks that stop working with two instances are *correctness* problems that appear the moment you add redundancy.
3. **Do the cheap, high-leverage things first** (backups, monitoring, paid model, deadlines) before architecture changes.
4. **Change one thing at a time**, behind evals and load tests, with a rollback.
5. **Prefer boring technology** (Postgres, Redis, a load balancer) over clever new components.
6. **Every stage must leave the system working** and no more complex than the problem requires.

## 32.1 Stage 0: the system today

```
Browser ─► Caddy ─► web (Next.js)
                └─► api (FastAPI + LangGraph, ONE process/container) ─► Postgres (one container, one volume)
                                  └─► mcp (ONE process) ─► SerpAPI
                                  └─► OpenRouter (free model)
```

Single VM, Docker Compose, hardened containers, no published ports but Caddy, health-gated startup, metrics/trace/audit built in locally, offline evals.

### Inventory of in-process state (the scaling blockers)

| State | Where | What breaks with N > 1 instances | Shared-state fix |
|---|---|---|---|
| Per-IP auth limiter (`ip_limiter`) | API memory | each instance allows its own 30/min → limit × N | Redis counters |
| Chat and buy-link limiters | API memory | per-user limit × N (and varies by which instance you hit) | Redis |
| Login failure counter (`FailureCounter`) | API memory | lockout needs 5 failures *per instance*, weakening brute-force defence | Redis (or DB) |
| `active_conversations` lock | API memory | two instances can run the *same* conversation concurrently → interleaved graph runs, duplicate outfits | DB conditional update or Redis lock |
| `ReplayGuard` (used `jti`s) | MCP memory | a captured token can be replayed once per MCP instance | Redis `SET NX EX` |
| MCP rate limiter and `CreditLedger` | MCP memory | per-user and global **credit caps × N**: the cost-protection guarantee breaks | Redis (atomic counters) |
| Search/link/product-ref caches | MCP memory | hit rate drops (each instance has its own cache); **`detail_refs` is also needed by `get_buy_link`: a buy-link request landing on a different instance than the search gets "Unknown or expired product_id"** | Redis (shared) |
| Prometheus counters | each process | fine (Prometheus scrapes and sums), but gauges like `ACTIVE_TURNS` are per instance | aggregate with `sum()` |
| LangGraph state | Postgres | **no problem**: already shared | |
| Conversation/outfit data | Postgres | no problem | |

The `detail_refs` row is the sharpest: **a functional bug, not just a weaker limit.** (Today with one MCP instance it works.) Remember to list it first in an interview; it shows you understand the real coupling.

## 32.2 Stage 1: harden the single node (do this before anything else)

These are the highest value-per-effort items; none changes the architecture.

| Item | Why | Effort |
|---|---|---|
| **Automated Postgres backups** (`pg_dump` cron to off-box storage) + a tested restore | the only copy of user data lives in one Docker volume | hours |
| **CI pipeline** (Chapter 28): tests, evals, image build, scans | every later stage depends on safe change | a day |
| **Paid model** + quotas/budget alerts | the free tier (50 requests/day) cannot serve users | config |
| **Token usage metrics** (`usage` from responses) and cost dashboard | you cannot manage cost you do not measure | hours |
| **Per-turn wall-clock deadline** in `chat.send` | a stuck provider call ties up a thread for minutes | hours |
| **External uptime and certificate monitoring**; alert rules (Alertmanager) | outages are noticed by users first | a day |
| **Alerts on credit/limit/auth metrics** | catches abuse (Chapter 28 postmortem example) | hours |
| **Separate DB roles** (migration owner vs app runtime) | the audit triggers mean little if the app can drop them | hours |
| **Log shipping and rotation** (Loki or a managed service) | JSON logs only exist in container output | a day |
| **CSP and extra security headers** | cheap XSS blast-radius reduction | hours |
| **Email verification, password reset, optional MFA** (or SSO) | account takeover risk for real users | days |
| **Account-erasure feature** (including checkpoints) | privacy obligations | a day |
| **`BUY_LINKS` counter + dashboards for conversion** | observability gaps | an hour |
| **Anchor audit-chain head hashes externally** | closes the "rewrite everything" gap | hours |

**Capacity after Stage 1 (single node):** from Chapter 30's estimate (~9 concurrent turns at 50k MAU) one API process suffices. The expected first limits: **search credits** (cost), **model rate limits**, and **availability** (one VM).

## 32.3 Stage 2: move shared state to Redis

Introduce **Redis** (managed, or a container with a volume and `requirepass`; private network only). It is the standard home for counters, short-lived keys with TTL, locks and caches.

### 2a. Rate limiters and lockouts (API and MCP)

Keep the *interface* (`check(key)`, `ensure_allowed`, `record_failure`, `clear`) and swap the storage, so call sites do not change:

```python
import time, uuid
import redis

class RedisSlidingWindow:
    """Same interface as throttle.SlidingWindow, but shared by every API instance."""
    def __init__(self, r: redis.Redis, name: str, limit: int, window_s: int):
        self.r, self.name, self.limit, self.window_s = r, name, limit, window_s

    def check(self, key: str) -> None:
        now = time.time()
        k = f"rl:{self.name}:{key}"
        pipe = self.r.pipeline()
        pipe.zremrangebyscore(k, 0, now - self.window_s)          # drop expired events
        pipe.zadd(k, {uuid.uuid4().hex: now})                     # record this event
        pipe.zcard(k)                                             # how many in the window now
        pipe.expire(k, self.window_s)                             # idle keys disappear (fixes the unbounded-keys issue)
        _, _, count, _ = pipe.execute()
        if count > self.limit:
            oldest = self.r.zrange(k, 0, 0, withscores=True)[0][1]
            raise TooManyAttempts(max(1, int(oldest + self.window_s - now) + 1))
```

Notes: the pipeline is not a single atomic script, so under extreme races the count can be off by a little (a Lua script makes it exact); a *denied* request still adds an event (stricter than the in-memory version: remove it on denial if you want parity); **`expire` removes idle keys**, solving the "keys never deleted" growth noted in Chapter 3. Decide **fail-open vs fail-closed** if Redis is down: for the **login lockout and credit ledger, fail closed** (or fall back to a conservative in-process limiter); for chat message limits, fail open with an alert.

### 2b. The "one turn at a time" lock

An in-memory `set` cannot protect across instances. Two good options:

**Database conditional update (simple, durable, crash-safe via expiry):**

```sql
ALTER TABLE conversations ADD COLUMN busy_until timestamptz;
```
```python
# acquire: atomic; succeeds only if no live lease exists
row = conn.execute(
    "UPDATE conversations SET busy_until = now() + interval '3 minutes' "
    "WHERE id = %s AND user_id = %s AND (busy_until IS NULL OR busy_until < now()) RETURNING id",
    (cid, user_id)).fetchone()
if row is None:
    raise HTTPException(409, "Still working on your previous message. Please wait a moment.")
# release (in the generator's finally): 
conn.execute("UPDATE conversations SET busy_until = NULL WHERE id = %s", (cid,))
```

The **lease expiry** means a crashed instance cannot leave a conversation stuck forever (the in-memory version's `finally` protects against disconnects but not against a process kill). **Redis alternative:** `SET lock:conv:<id> <random> NX EX 180` and release with a compare-and-delete script; add **fencing** if a stale holder could still write.

### 2c. MCP: replay guard, limits, ledger, caches

```python
# ReplayGuard on Redis: atomic "first use" check with automatic expiry
async def first_use(self, jti: str, ttl_s: int) -> bool:
    return bool(await self.r.set(f"jti:{jti}", 1, nx=True, ex=ttl_s))     # False if it already existed
```

* **CreditLedger**: `INCR credits:{yyyymmdd}:user:{id}` and `INCR credits:{yyyymmdd}:global`; compare against caps; `EXPIREAT` at the next UTC midnight; use a Lua script to check-and-increment atomically (so a refused spend is never counted: the in-memory test `test_a_refused_spend_is_not_counted` states the requirement).
* **Rate limiter**: as 2a.
* **Caches**: store serialised `SearchProductsResult`/`DetailRef` JSON under keys with TTL (`SET key value EX 21600`). This **fixes the cross-instance `detail_refs` bug** and restores the cache hit rate. Add **single-flight** (a short `SET NX` lock per query key) so ten simultaneous identical searches make **one** paid call.
* Keep the per-instance fast path (a small in-process LRU) in front of Redis if latency matters.

Tests: reuse the existing tests by parametrising the store (in-memory vs Redis via a test container); add a multi-instance test with two app objects sharing one Redis and prove limits and replay protection hold across them.

## 32.4 Stage 3: several API instances behind a load balancer

With state externalised the API is **stateless** and replicable.

```
Browser ─► Caddy ─► web (xN)
                └─► api (xN)  ─► Postgres (shared)  ─► Redis (shared)
                              └─► mcp (xM)         ─► SerpAPI
```

Changes:

1. **Caddy upstreams**: `reverse_proxy api1:8000 api2:8000 { lb_policy least_conn; health_uri /health; flush_interval -1 }` (Compose `deploy.replicas` / `--scale` give you service-name DNS round-robin; explicit upstream lists with active health checks are more robust). No stickiness is needed because conversation state is in Postgres and the turn lock is shared.
2. **Connection budget**: each API instance has two pools (`max_size` 10 + 5). With N instances: `15 × N ≤ max_connections - reserve`. With default `max_connections=100`, **N ≤ 5** before you need **PgBouncer** (transaction pooling is compatible with the main pool; **the LangGraph saver uses autocommit connections and session features; test it or give it session pooling**).
3. **Graceful deploys**: rolling restart one instance at a time; `terminationGracePeriod`/`stop_grace_period` ≥ longest turn (90 s); the readiness check drains first.
4. **Thread-pool sizing**: each in-flight turn holds a worker thread; per-process limit ≈ 40 threads by default; raise cautiously or add instances. Capacity ≈ `instances × threads ÷ avg_turn_seconds` (e.g. 3 × 40 ÷ 30 = **4 turns/s**).
5. **Trust boundaries stay**: MCP instances remain private; the API has no published port.
6. **Observability**: Prometheus scrapes each instance; use `sum by` aggregations; add `instance` labels (a bounded label); trace ids already correlate across instances.
7. **Zero-downtime migrations**: run migrations as a one-off job *before* rolling the new code, with expand/contract discipline (Chapter 17), not at every instance's startup.

### Performance upgrades worth doing at this stage

* **Reuse HTTP connections to the tool server**: today each search opens a new client and event loop (`asyncio.run` per call); a shared client per worker thread (or move the graph's node to `async` and use one pooled `httpx.AsyncClient`) removes handshake latency.
* **Async agent**: LangGraph supports async nodes and an async Postgres saver; converting the stylist graph to `async def` nodes, `graph.astream`, and `AsyncPostgresSaver` lets one event loop serve far more concurrent turns than a 40-thread pool (turns are mostly waiting). This is a larger refactor; justify it with load-test data.
* **Prompt/token trimming**, **caching** at the gateway, **parallel planning calls** where independent.
* **Move the search stage to partial-result streaming** (show outfits as each completes).

## 32.5 Stage 4: scale and protect the database

* **Managed Postgres** (RDS/Cloud SQL/Neon/Supabase) with automated backups, PITR, patching, a standby in another AZ. Move credentials to a secret manager; TLS to the database.
* **Checkpoint tables growth**: LangGraph stores conversation state; at ~15 KB per conversation (Chapter 30's estimate) that is ~3 GB/month at 50k MAU. Add a **retention job** (delete threads older than N days; keep outfits), and consider a **separate database** for checkpoints so heavy churn does not compete with account queries.
* **Audit log**: partition by month; **export verified segments** to WORM storage keeping boundary hashes; **anchor** the head daily; consider sharded chains if the global advisory lock becomes a bottleneck (measure `audit.append` p95).
* **Indexes**: confirm with `EXPLAIN ANALYZE` on production-size data; add a partial index for non-disabled users if needed; check the recent-outfits and ownership queries.
* **Read replicas** for `GET /conversations` and history if read load grows; handle replication lag (read-your-writes: after sending a message, read from the primary).
* **Connection pooling** (PgBouncer) and `max_connections` tuning.
* **Housekeeping**: expired `refresh_tokens` cleanup, `VACUUM`/autovacuum monitoring, bloat checks.
* **Row-level security** as a backstop for tenant/user isolation if the product becomes multi-tenant.

## 32.6 Stage 5: a model and tools gateway

When more than one service or team uses models and tools, or when provider reliability matters:

* **LLM gateway** (Chapter 31): central keys, per-user budgets, **fallback across providers/models**, retry policy, exact + semantic caching for safe prompts, token/cost accounting, PII redaction, streaming pass-through. Replace `get_llm`'s direct client with a gateway client (the seam already exists).
* **Model routing**: a small model for `gather_prefs` (extraction), a stronger one for `plan_outfits`; evaluate with the offline + live suites; route by stage.
* **Search provider abstraction with fallback**: the adapter seam (`providers/serpapi.py`) makes a second provider (or a first-party catalogue/affiliate API) straightforward; add **circuit breakers** and a **degraded mode** that returns cached results when credits run out.
* **Caching strategy for search**: larger shared cache in Redis keyed by normalised query; **popular query precompute** (top occasions × colours) during off-peak; TTL tuned to price volatility.
* **Batch endpoints** for non-urgent work (evals, embeddings).
* **Cost controls**: per-tenant budgets, anomaly alerts, kill switch.
* **Tool server scale-out**: multiple MCP instances (they are stateless after Stage 2), still private; service-to-service **mTLS or the existing signed tokens** with a shared replay store.

## 32.7 Stage 6: asynchronous and long-running work

For features like **"try it on me"** and larger research-style tasks (Chapter 31, cases 4 and 6):

* **Job table + worker pool** using `FOR UPDATE SKIP LOCKED`, or a queue (SQS/Redis streams/Celery/Arq) when volume grows.
* **Object storage** for images/artifacts, **signed URLs**, **moderation**, **retention**.
* **Idempotency keys**, per-user concurrency limits, global provider-rate budgets, dead-letter handling.
* **Progress delivery** (SSE or polling) reusing the existing event pattern.
* **Autoscale workers** on queue depth.

The chat turn itself can also move behind a queue if you want strict control of provider concurrency, with the SSE endpoint subscribing to progress events (more moving parts; only if load demands).

## 32.8 Stage 7: availability, multi-AZ and disaster recovery

* **Two or more instances of every tier across availability zones** behind a managed load balancer (mind its idle timeout vs streaming: Chapter 27).
* **Managed Redis with replication**, managed Postgres with a standby.
* **Infrastructure as Code** (Terraform) and **GitOps**; immutable images by SHA; automated rollbacks.
* **Secrets in a secret manager**, workload identity instead of long-lived keys.
* **Kubernetes or a managed container platform** *only if* the number of services/teams justifies it; the app is already 12-factor and containerised, so porting is mostly manifests (Chapter 26).
* **CDN/WAF** in front; bot defence on signup; DDoS protection.
* **DR**: cross-region backups, a rehearsed restore, a documented RTO/RPO; multi-region active-passive only if the business case demands it.
* **SLOs and error budgets** with on-call, runbooks, and postmortems (Chapter 28).

## 32.9 Stage 8: product and data maturity

* **Evaluation in production**: sampled conversations judged by a calibrated LLM judge plus human review; dashboards on delivery rate, confidence mix, Buy-click rate, cost per conversation; **canary** prompt/model rollouts with automatic rollback criteria.
* **Feedback loop**: thumbs and "wrong item" buttons linked to trace ids; failed cases become eval cases (Chapter 12).
* **Personalisation and long-term memory**: remembered sizes, budgets, preferences (with consent, deletion, and minimisation); retrieval of style knowledge (Chapter 10).
* **Taste judge** (model-based and human) to measure outfit quality beyond guarantees.
* **Affiliate/retailer integrations** replacing scraped shopping results (better data, direct links, revenue, legal clarity): product feed ingestion, price/availability freshness, a real catalogue in Postgres with search (and the verifier then runs on structured attributes, not titles; colour confirmation jumps from ~11% to ~100%).
* **Analytics warehouse** (export events to BigQuery/ClickHouse) for funnel analysis.
* **Internationalisation**: languages (Hinglish input), currencies.

## 32.10 Capacity summary by stage (illustrative)

| Stage | Concurrent heavy turns supported | First limit you hit | Availability |
|---|---|---|---|
| 0 (today) | ~40 (one process thread pool) but the free model allows ~8 conversations/day | model quota and search credits | single VM, minutes of downtime per deploy |
| 1 (hardened single node) | ~40 | paid-model rate limits, search cost | one VM; backups and alerts |
| 2-3 (Redis + 3 API instances) | ~120 (3 × 40), more with async | Postgres connections, search quota | survives an instance failure |
| 4 (managed DB + retention) | same | DB write/IO, checkpoint size | DB failover |
| 5 (gateway, routing, search fallback) | provider-limited | provider TPM/RPM and spend | provider failover |
| 6 (async workers) | queue-bound, elastic | worker count, provider limits | resilient to bursts |
| 7 (multi-AZ, IaC) | elastic | cost | multi-AZ; DR-ready |

(The numbers are for reasoning, not promises; replace them with load-test results.)

## 32.11 The prioritised backlog (what you would do next, and why)

| Priority | Item | Reason |
|---|---|---|
| **P0** | Backups + tested restore | irrecoverable data loss risk |
| **P0** | Rotate any exposed keys; secrets hygiene; separate DB roles | active security exposure |
| **P0** | Paid model, quotas, budget alerts | cannot serve users otherwise |
| **P0** | CI with tests, evals, scans | every other change depends on it |
| **P1** | Per-turn deadline; token metrics; alerts; uptime checks | operability and cost control |
| **P1** | Redis for limiters, replay guard, ledger, caches; DB lease for turn lock | prerequisite for redundancy; fixes the `detail_refs` coupling |
| **P1** | Account basics: email verification, reset, MFA/SSO, erasure incl. checkpoints | trust and compliance |
| **P2** | 2-3 API instances, rolling deploys, migrations as a release step | availability |
| **P2** | Managed Postgres, retention, audit anchoring/partitioning | durability and growth |
| **P2** | Real-model eval suite + taste judge + production sampling | quality visibility |
| **P3** | Model gateway and routing; search fallback/affiliate feeds | cost, reliability, data quality |
| **P3** | Async jobs for try-on; image safety/privacy work | new feature |
| **P3** | Async agent refactor; Kubernetes/IaC | only if load or org size demands |

An interviewer-friendly one-liner: *"First I'd make the single node safe and observable: backups, CI, a paid model, alerts. Then I'd move the in-process state into Redis and Postgres leases, which is the actual blocker to running two instances. Only then would I add instances, a managed database and a model gateway, with load tests in demo mode at each step."*

## 32.12 Load-test plan (demo mode, free)

1. Run the stack in `BACKEND_MODE=demo`; seed N accounts.
2. Ramp virtual users from 1 to 100 (Locust: Chapter 28), each user respecting 10 messages/min.
3. Record p50/p95/p99 turn time, error rate, thread-pool saturation, DB connections, CPU/memory, `stylist_active_chat_turns`.
4. Identify the first bottleneck; change *one* thing (instances, pool size, async); repeat.
5. Test failure: kill an API instance mid-stream; stop the tool server; stop Redis; verify behaviour and messages.
6. Run a soak test (hours) to find leaks and checkpoint growth.
7. Only then do a **tiny** live-model run to calibrate real latency and token usage, and update the capacity table.

## Common mistakes

* Adding instances before externalising state (limits and locks silently weaken; buy-link lookups fail).
* Scaling the app tier while the real limit is an external quota.
* Jumping to Kubernetes/microservices without a measured need.
* Forgetting the DB connection budget (`instances × pool size`).
* No load test; capacity guessed.
* Treating retention and privacy as later problems while checkpoints accumulate user text.
* Making many changes at once, so regressions cannot be attributed.

## Summary

* Scale in stages: harden → externalise state → replicate the API → scale and protect the database → gateway and routing → async work → multi-AZ and DR → product maturity.
* The true blockers to running two instances are in-process rate limiters, the turn lock, the replay guard, the credit ledger and the tool server's caches (especially `detail_refs`, a functional coupling).
* Redis plus a database lease solve them while keeping existing interfaces and tests.
* Capacity is `instances × threads ÷ turn time`; the first practical limits are search credits and model quotas.
* Keep a prioritised backlog and justify every step with measurements.

## Key terms

*stateless service, shared state, lease, fencing, single-flight, connection budget, PgBouncer, retention, partitioning, read replica, gateway, circuit breaker, async worker, multi-AZ, RTO/RPO, canary, capacity plan.*

## Interview questions

1. What would break if you ran three copies of the API today? Of the tool server?
2. How would you make the "one turn at a time" guarantee work across instances?
3. Compute the connection budget for 4 API instances with these pool settings.
4. What would you do first to make this production-ready? Next? Why in that order?
5. How would you turn the thread-per-turn model into something that scales to thousands of concurrent streams?
6. How do you keep the credit-cap guarantee when the MCP server is replicated?
7. How would you test the scaled system without spending money on model calls?

## Exercises

1. Implement `RedisSlidingWindow` behind the existing limiter interface and run the existing limiter tests against both implementations.
2. Implement the `busy_until` lease for conversations with a migration and tests (including crash expiry).
3. Make `detail_refs` shared via Redis and write a two-instance test proving a buy link works when search and buy hit different instances.
4. Convert one graph node and the saver to async and measure concurrent-turn capacity in demo mode before and after.
5. Write the scaled architecture diagram and the runbook for "an API instance died mid-stream".
