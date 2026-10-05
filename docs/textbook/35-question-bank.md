# Chapter 35. Question Bank

> **How to use this chapter.** Cover the answer, say yours out loud for 30-90 seconds, then compare. The model answers are deliberately short: they are the *spine* of a good answer; add an example from this project (and a trade-off) to make each one yours. Each answer points to the chapter with the full treatment. Practise the project-specific section last, because it combines everything.

---

## The four questions that come up everywhere

Full answers (method, evidence, worked example, 90-second script) are in [Chapter 37](37-the-four-questions.md). The one-paragraph versions:

**Q1. Why did the retrieval fail?** Decide whether retrieval or generation broke, then walk the ladder: query → did the source return anything → filters → parsing → verification/ranking → cache/state staleness → access/limits → did it reach the next stage. In this app read `query_used`, `warnings`, the `rejected` reasons and planner `notes`, and the cache/limit/error metrics via the trace id; in RAG check ingestion, chunking, embeddings, hybrid search, ACL filters, k and reranking with recall@k on a labelled set. Fix at the broken layer, then add an eval case and a metric.

**Q2. How would you evaluate this system?** Map each promise (four outfits, within budget, verified, men's only, honest uncertainty, bounded cost, safe) to a measurement: layered tests, a real-and-adversarial dataset with property-based expectations and a held-out set, deterministic scorers with hard gates versus soft signals, a calibrated LLM judge and human review for quality, honest statistics (13/13 ≈ 77% lower bound; demo mode proves plumbing only), live evals within budget, canaries, SLIs, a feedback loop, and a red-team suite.

**Q3. What happens when traffic increases 100x?** Baseline then rates: ~840 concurrent turns, ~3M search credits/day, ~150 model calls/s, hundreds of writes/s, ~300 GB/month checkpoints. First cost breaks, then in-process state (limits, locks, replay guard, caches) with multiple instances, then provider limits and tails, thread-per-turn concurrency, Postgres connections and the audit lock, then redundancy and abuse. Act differently at 2x, 10x and 100x, and confirm with a demo-mode load test.

**Q4. Why is the model hallucinating?** Classify the failure; remember models produce plausible text and forced fields invite invention; check whether the truth was in the context; vary one factor over several runs; look for injected instructions; fix by grounding, removing the model from factual claims, constraining outputs, verifying in code, citing, right-sizing, and measuring groundedness. Here the model never states product facts, and `rationale` text is the one ungrounded spot.

---

## A. Programming foundations (Chapter 2)

**A1. What does `b = a` do when `a` is a list?** It binds a second name to the *same* object; mutating through either name changes both. Copy with `a.copy()`/`list(a)` (shallow) or `copy.deepcopy` (nested). The project copies `prefs` before updating it in a graph node.

**A2. Mutable default argument trap?** Default values are evaluated once at function definition, so `def f(x, bucket=[])` shares one list across calls. Use `None` and create inside, or `default_factory` in dataclasses/Pydantic.

**A3. Concurrency vs parallelism? What is the GIL?** Concurrency is structuring work so many things progress (possibly on one core); parallelism is executing simultaneously on multiple cores. CPython's GIL lets one thread run Python bytecode at a time, so threads help I/O-bound work (released during I/O) but not CPU-bound Python; use processes for CPU work.

**A4. Threads, asyncio or processes for an AI backend?** It is mostly I/O-bound (waiting on models and APIs): threads or asyncio. The project uses a thread pool for 8 parallel searches and sync endpoints in FastAPI's thread pool; the tool server is async. CPU-heavy work (Argon2) belongs in worker threads/processes, not the event loop.

**A5. What happens if you call a blocking function inside `async def`?** It blocks the event loop, stalling every other request on that loop. Use async libraries, a `def` endpoint (thread pool) or `run_in_threadpool`.

**A6. What is a race condition? Two fixes.** Correctness depends on timing of concurrent operations (e.g. lost update). Fix with mutual exclusion (locks, DB row locks/advisory locks), atomic operations, or constraints. Examples here: the active-turn lock, `FOR UPDATE` in token rotation, the audit advisory lock.

**A7. What is idempotency and why does it matter?** Repeating an operation has the same effect as doing it once. Networks retry, so non-idempotent actions need idempotency keys or unique constraints (`UNIQUE (conversation_id, batch, position)`).

**A8. Generators: what and why?** Functions with `yield` produce values lazily and pause between them. They enable streaming and constant memory; the chat endpoint streams SSE events from a generator, and `finally` runs when the client disconnects.

**A9. `??` vs `||` in JavaScript?** `??` falls back only for `null`/`undefined`; `||` falls back for any falsy value (`''`, `0`). With `NEXT_PUBLIC_API_URL=""` meaning "same origin", `??` correctly keeps the empty string.

**A10. Why validate at the boundary?** Untrusted data (HTTP bodies, LLM output, search results) is parsed into typed objects once at the edge; inside, code can rely on the types. Pydantic does it in this repo.

## B. Data structures and algorithms (Chapters 3-4)

**B1. Complexity of `x in list` vs `x in set`?** O(n) vs O(1) average.

**B2. How does a hash table handle collisions? Load factor?** Chaining or open addressing (CPython). Load factor = entries/slots; resizing keeps it low so operations stay O(1) amortised. Randomised string hashing blocks hash-flooding DoS.

**B3. Implement an LRU cache.** Hash map + doubly linked list (or `OrderedDict` with `move_to_end`): O(1) get/put, evict the least recently used. Note the repo's `TTLCache` evicts FIFO.

**B4. Why do databases use B-trees?** Wide, shallow, balanced trees match disk pages: a lookup among billions needs a handful of page reads; they support range scans and ordering.

**B5. BFS vs DFS?** BFS uses a queue and finds shortest paths in unweighted graphs; DFS uses a stack/recursion and suits cycle detection, topological sort, backtracking. Always track `seen`.

**B6. Detect a cycle in a linked list / directed graph.** Floyd's tortoise-and-hare for lists; DFS with colours or Kahn's topological sort (leftover nodes = cycle) for directed graphs.

**B7. Design the data structure for "10 requests/minute per user".** Per-key deque of timestamps (sliding window log) or a token bucket; O(1) amortised; bound memory; distribute with Redis for several instances.

**B8. Two Sum in O(n)?** One pass with a hash map from value to index, checking `target - x` first.

**B9. Longest substring without repeating characters?** Sliding window with a map of last-seen indexes, moving `start` past the previous occurrence: O(n).

**B10. When is greedy correct? Counter-example?** When a greedy-choice property holds (exchange argument), e.g. interval scheduling by end time. Coin change with coins {1,3,4}, amount 6 breaks greedy (4+1+1 vs 3+3).

**B11. Recipe for dynamic programming?** Define the state in words, write the transition, base cases, order of computation, extract the answer, then optimise space. Overlapping subproblems + optimal substructure.

**B12. Binary search pitfalls?** Off-by-one and infinite loops; use one invariant-based template (`lo=0, hi=n`, `while lo<hi`). Also "binary search on the answer" with a monotonic predicate.

**B13. Top-k from a stream?** Min-heap of size k: O(n log k). For vector search, exact top-k is O(N·d); ANN indexes trade accuracy for speed.

**B14. Explain exponential backoff with jitter.** Wait `base·2^attempt` plus randomness so many clients do not retry in lockstep (thundering herd); cap the delay and the attempts; honour `Retry-After`.

**B15. Prove `clamp_to_budget` never exceeds the budget.** With scale `s = B/(a+b)`, `floor(a·s)+floor(b·s) ≤ (a+b)·s = B`.

## C. LLMs and prompting (Chapters 6-7)

**C1. How does an LLM generate text?** It predicts a probability distribution over the next token given the context, picks one (sampling/greedy), appends it, and repeats. Hidden state is only the text in the context window.

**C2. What are tokens and why do they matter?** Sub-word chunks from a fixed vocabulary; they determine cost, context limits, speed, and odd failures (letter counting, arithmetic).

**C3. Temperature, top-p, top-k?** Temperature rescales logits before softmax (low = near-deterministic, high = diverse); top-k and top-p restrict sampling to likely tokens. Low for extraction, higher for creative text. "Temperature 0" is still not perfectly deterministic.

**C4. What is attention? Why O(n²)?** Each token computes weights over all other tokens' values via `softmax(QKᵀ/√d)V`; comparing every pair of tokens costs quadratic time/memory in context length; KV caching and optimised kernels mitigate it.

**C5. Pre-training vs SFT vs RLHF?** Pre-training: next-token prediction on huge text. SFT: learn from instruction-response pairs. RLHF/DPO: optimise preferences for helpfulness and safety. RL on verifiable tasks produces reasoning models.

**C6. Why do models hallucinate, and mitigations?** They maximise plausibility, not truth. Ground in retrieved/tool data, verify in code, constrain outputs, allow abstention, cite sources, lower temperature for factual tasks.

**C7. The API is stateless. How do conversations work?** The client resends history each call. Here, LangGraph's Postgres checkpointer stores state per thread id; cost grows with history unless trimmed or summarised.

**C8. What is the context window and "lost in the middle"?** Max tokens (input+output) per call; models use information in the middle of long contexts less reliably, and irrelevant text distracts: curate the context.

**C9. What is prompt caching?** Providers reuse the processed prefix of identical prompt starts at a discount; put stable content first, variable content last; verify via cache-read tokens in `usage`.

**C10. How do you get reliable JSON from an LLM?** Constrain (JSON-schema outputs or tool-calling), validate (Pydantic), retry/repair with bounds, fail safely; log failure rates. This repo uses tool-calling because the free model rejects `json_schema` and JSON mode returned nulls.

**C11. JSON mode vs schema-constrained output?** JSON mode guarantees valid JSON syntax only; schema-constrained decoding enforces your schema's types and required fields.

**C12. Few-shot vs zero-shot; chain-of-thought?** Few-shot adds examples to convey format/judgement (costs tokens every call); CoT asks for step-by-step reasoning (reasoning models do this internally with an effort setting).

**C13. How do you manage prompts in production?** Versioned files, PR review, evals before/after, version pinned in code (`load_prompt("plan_outfits", 2)`), changelog, rollback by changing the pin.

**C14. Why are field descriptions part of the prompt?** The schema is sent to the model; names, enums and descriptions steer it.

**C15. When fine-tune vs RAG vs prompt?** Prompt/few-shot first; RAG for facts/documents/citations/permissions; fine-tune for style/format/narrow behaviour at volume after evals show a gap.

**C16. What are reasoning models and their trade-offs?** They spend hidden tokens thinking before answering; better on multi-step problems, higher cost/latency (thinking billed as output), some parameters restricted.

**C17. Open-weight vs closed models?** Open weights allow self-hosting, privacy and fixed cost at scale but need GPU ops and may lag the frontier; closed APIs are easy and strong but involve data-sharing and vendor dependence.

**C18. Why not use the model for arithmetic?** Token-level view, no calculator: use code. This app enforces budgets and totals in Python.

**C19. What is semantic versus exact caching of LLM calls?** Exact: identical inputs; semantic: similar queries by embedding similarity; semantic risks wrong reuse (partition by tenant, high thresholds, only safe content).

**C20. How would you handle a provider model deprecation?** Abstraction seam, pinned versions, evals runnable on candidates, fallback, canary, communicate. Treat (model, prompt, schema) as one versioned unit.

## D. Tools, MCP, agents, LangGraph (Chapters 8-9)

**D1. Explain function calling.** You send tool schemas; the model returns structured tool-call requests; your code validates and executes them and returns results; the model continues. The model never executes anything.

**D2. What makes a good tool?** Clear verb-noun name, caller-oriented description with limits/cost, typed constrained parameters, concise structured results, actionable safe errors, honest annotations (read-only/idempotent), bounded behaviour, least privilege.

**D3. What is MCP and why?** An open protocol (JSON-RPC over stdio or streamable HTTP) for AI apps to discover and call tools/resources/prompts on servers: N×M integrations become N+M, with schemas and a standard auth story.

**D4. MCP primitives?** Tools (model-controlled functions), resources (app-controlled read-only data), prompts (user-controlled templates); clients can offer sampling, roots, elicitation.

**D5. Why is the tool server separate here even though the LLM doesn't pick tools?** A privilege boundary: it holds the search key, fetches URLs, enforces limits, has no public address and only a public key. The graph calls tools deterministically.

**D6. How is the MCP server authenticated?** Fresh RS256 JWT per HTTP request (30 s, unique `jti`) minted by the API with a private key; the server verifies with the public key, caps lifetime, refuses replayed `jti`s, checks Host/Origin, rate-limits and caps credits per user.

**D7. Prompt injection via tool results?** Tool output is untrusted text that can contain instructions; limit tool power, break the lethal trifecta, constrain outputs, verify in code, confirm risky actions.

**D8. Workflow vs agent?** Workflow: code fixes the steps, the model fills them; agent: the model decides next steps in a loop. Start with the simplest; use agents only for open-ended tasks with bounded cost and recoverable errors.

**D9. LangGraph in one minute.** A state graph: shared state, node functions returning partial updates, edges (conditional ones route on state), reducers for merging, a checkpointer saving state per thread id after each step, interrupts to pause for humans.

**D10. What exactly happens on `interrupt()`?** The graph saves its checkpoint and returns to the caller with the payload; nothing runs. Resuming with `Command(resume=value)` re-executes the interrupted node from the top, with `interrupt()` returning the value, so side effects before it run twice.

**D11. Reducers?** Functions that merge a node's update into a channel: `add_messages` appends; keys without a reducer are overwritten.

**D12. How do you stop agent loops?** Iteration caps, recursion limits, time/token/cost budgets, deterministic routing, terminating conditions in code (`MAX_RETRIES`).

**D13. Why does `rank_and_validate` repeat checks?** Defence in depth: the last node before the user re-checks invariants so a bug upstream cannot surface wrong outfits.

**D14. How do you test agents without a real model?** Scripted fake models, unit tests of nodes/routers, graph tests with `MemorySaver`, full-stack tests with real Postgres, property tests, then live evals.

**D15. Multi-agent: when?** Context isolation, parallelism, specialised tools/models, security separation; costs include tokens, latency and compounding errors: one agent with good tools first.

## E. RAG, evals, observability, reliability, cost (Chapters 10-14)

**E1. Design a RAG pipeline.** Parse and clean, chunk with overlap and metadata, embed, index (pgvector/HNSW + BM25); query: rewrite, hybrid retrieve with ACL filter, rerank, assemble context, generate with citations, verify groundedness, evaluate retrieval and generation separately.

**E2. Dense vs sparse retrieval?** Dense captures meaning, misses exact tokens; BM25 captures exact terms, misses paraphrases; combine with RRF and rerank.

**E3. How to choose chunk size?** Trade precision vs context; start 200-500 tokens with overlap; measure recall@k on your questions.

**E4. Per-user permissions in RAG?** Store ACLs as metadata and filter at retrieval time by the requester's groups; never rely on the model to hide content; partition caches by user/tenant.

**E5. How to debug a bad RAG answer?** Was the right chunk retrieved? If not, fix retrieval; if yes, fix prompting/generation.

**E6. How do you evaluate an LLM feature?** Dataset (real, categorised, property-based expectations), deterministic scorers where possible, calibrated LLM judges and human review for subjective quality, gates vs soft signals in CI, online monitoring, red-team suite.

**E7. LLM-as-judge pitfalls?** Position, verbosity and self-preference biases; calibrate against human labels, use rubrics and pairwise comparisons, different/stronger judge.

**E8. 13/13 evals pass: ship?** Not on that alone: with 13 cases the 95% lower bound on the pass rate is ~77%; check coverage, held-out cases, real-model runs, and what the eval does not measure (demo mode proves plumbing, not model quality).

**E9. Logs, metrics, traces?** Logs: detailed events; metrics: aggregate trends; traces: one request's path. Linked by trace id.

**E10. Label cardinality?** Each unique label combination is a time series; high-cardinality labels (user ids, raw URLs) explode storage and leak data. Use route templates.

**E11. Write a PromQL for p95 latency.** `histogram_quantile(0.95, sum by (le) (rate(stylist_chat_turn_seconds_bucket[5m])))`.

**E12. SLI/SLO/error budget?** Measured indicator, target over a window, allowed unreliability (1 - SLO) that guides risk-taking.

**E13. Retry storms?** Layered retries multiply load (3×3×3 = 27). Retry only transient, idempotent operations with backoff and caps at known layers.

**E14. Circuit breaker vs bulkhead?** Breaker stops calling a failing dependency and probes recovery; bulkhead isolates resource pools so one dependency cannot starve others.

**E15. Reduce LLM cost?** Don't call (code, caches), send fewer tokens, prefix caching, right-size/route models, control effort and output length, batch non-urgent work, then fine-tune/self-host; measure cost per successful task.

**E16. Why can search cost exceed model cost?** 8 searches per planning round at per-credit prices vs a few thousand tokens; so protect credits with caching and caps.

**E17. Tail latency of fan-out?** Total time is the max; with 8 calls each 1% slow, P(at least one slow) ≈ 7.7%: timeouts, hedging, partial results, caching.

**E18. Denial of wallet?** Abuse or bugs that drive paid API usage; defend with auth, rate limits, quotas, ownership checks, bounded loops, budget alerts, kill switches.

## F. Web, networking, backend, frontend (Chapters 16-19)

**F1. What happens when you type a URL and press Enter?** DNS resolution, TCP connect, TLS handshake (SNI, certificate validation), HTTP request, server/proxy routing, response, rendering, further requests.

**F2. 401 vs 403 vs 404?** 401: not authenticated; 403: authenticated but forbidden; 404: not found (also used to hide existence). The API uses uniform 404 for not-yours resources.

**F3. Idempotent HTTP methods?** GET, HEAD, PUT, DELETE, OPTIONS; POST is not, so it needs idempotency keys when retried.

**F4. Explain CORS.** A browser rule: cross-origin reads need server opt-in via `Access-Control-Allow-*` headers (preflight for non-simple requests). It does not protect against non-browser clients.

**F5. Where to store tokens in a SPA?** Short-lived access token in memory (not auto-sent, so no CSRF; lost on reload), refresh token in an HttpOnly, Secure, SameSite cookie scoped to `/auth`; avoid `localStorage`.

**F6. CSRF and defences?** Forged cross-site requests using auto-sent cookies; defend with SameSite cookies, custom headers (`X-Requested-With`), CSRF tokens, Origin checks; header-authenticated APIs are not CSRF-prone.

**F7. SSE vs WebSocket vs polling?** SSE: server-to-client text stream over HTTP, simple, proxy-friendly; WebSocket: bidirectional, more infra; polling: simple but wasteful.

**F8. Why can streaming break behind a proxy?** Buffering/compression/idle timeouts; fix with `flush_interval -1`, `X-Accel-Buffering: no`, heartbeats, correct LB timeouts.

**F9. `X-Forwarded-For` trust?** Only trust it from known proxies (`FORWARDED_ALLOW_IPS`); otherwise clients can spoof IPs to dodge limits.

**F10. `def` vs `async def` in FastAPI?** `async def` runs on the event loop and must not block; `def` runs in a thread pool. Argon2 hashing is sync so it does not freeze the loop.

**F11. FastAPI dependencies?** Callables injected into endpoints (`Depends`), composable (auth → admin), overridable in tests.

**F12. Why a `create_app` factory?** Tests inject fakes (pool, model, search); production builds real ones; no import-time globals required.

**F13. React stale closure?** A callback captured old state; fix with functional updates or refs.

**F14. Why does Strict Mode double-run effects?** To expose non-idempotent effects/missing cleanup; in this app it exposed the need for a single-flight refresh.

**F15. `NEXT_PUBLIC_*`?** Inlined at build time into client JS, public; changing it requires a rebuild; never for secrets.

**F16. Why does the Buy button open a tab before the network call?** Pop-up blockers allow `window.open` only inside the user gesture; it opens blank, then navigates after the API responds; sets `opener = null`.

## G. Databases (Chapter 17)

**G1. ACID?** Atomicity, Consistency, Isolation, Durability.

**G2. Isolation levels and anomalies?** Read committed (default in Postgres), repeatable read, serializable; anomalies: dirty/non-repeatable/phantom reads, lost update, write skew.

**G3. How does `SELECT ... FOR UPDATE` help refresh-token rotation?** It locks the row so concurrent refreshes with the same token serialise; the second sees `used_at` set and is treated as replay.

**G4. Why commit before raising an HTTP error in login?** An exception rolls back the transaction, losing the audit record and failure counter; the code commits then raises.

**G5. Advisory locks?** Application-defined locks in the database; used to serialise audit appends and migrations across processes.

**G6. Index design for recent conversations?** `(user_id, updated_at DESC)` serves filter + order without a sort.

**G7. What is `EXPLAIN ANALYZE` telling you?** The executed plan, row estimates vs actual, timings; look for seq scans, sorts, bad estimates.

**G8. SQL injection prevention?** Parameterised queries; allow-list identifiers; least-privilege DB roles.

**G9. Why `timestamptz`, integer money, UUID keys?** Absolute instants; avoid float errors; non-guessable ids.

**G10. Zero-downtime migrations?** Expand → migrate → contract; backward compatible; never break the running version; concurrent index builds; migrations as a release step.

**G11. What does a connection pool do; exhaustion?** Reuses connections to avoid handshake cost and cap load; exhaustion (leaks, long transactions) hangs requests.

**G12. Backups, RPO, RTO?** `pg_dump` and WAL-based PITR; RPO = tolerable data loss; RTO = tolerable downtime; test restores.

**G13. When Redis?** Shared counters/limits, replay sets, caches, locks, queues; needed when scaling out stateful in-memory structures.

## H. Security (Chapters 20-22)

**H1. Hash vs encrypt vs sign?** Hash: one-way fingerprint; encrypt: reversible with a key; sign: authenticity/integrity with private key (verify with public).

**H2. Why Argon2id for passwords?** Memory- and time-hard with per-password salt, resisting GPU/ASIC guessing; fast hashes are wrong for low-entropy secrets.

**H3. Why plain SHA-256 for refresh tokens?** They are 384 random bits; brute force is infeasible, and a slow hash would only cost CPU.

**H4. JWT: structure and pitfalls?** `header.payload.signature` (Base64url, readable); pin algorithms, validate `iss/aud/exp`, require claims, avoid `alg:none` and RS→HS confusion, short lifetimes, no secrets inside, plan revocation/rotation.

**H5. HS256 vs RS256?** Shared secret (signer = verifier) vs private/public keys (verifier cannot mint). This app uses RS256 so the tool server can only verify.

**H6. Refresh-token rotation with reuse detection?** Each use replaces the token; reuse of a used token revokes the whole family (theft signal). False positives from two-tab races can be softened with a short grace window.

**H7. How does login avoid user enumeration?** Uniform error text, equal timing (dummy-hash verification), uniform status.

**H8. What is SSRF and the defences in `check_link`?** Server fetches attacker-chosen URLs; defend with https only, domain allow-list (dot-anchored suffix), public-IP check on all addresses, connect to the checked IP with the real Host/SNI (anti-rebinding), manual redirects re-validated, bounded reads.

**H9. DNS rebinding?** DNS answers a public IP at check time and an internal one at connect time; defeat by resolving once and pinning the IP; also Host-header validation on local servers.

**H10. What is IDOR and how is it prevented?** Accessing others' objects by id; ownership-scoped queries, uniform 404s, tests.

**H11. Prompt injection: direct vs indirect; defences?** Direct from the user, indirect hidden in data the model reads. Least privilege, no lethal trifecta, constrained outputs, deterministic verification, confirmation for risky actions, sanitised rendering, no secrets in context.

**H12. Lethal trifecta?** Private-data access + untrusted content exposure + external communication ability in one agent; remove at least one.

**H13. Secrets management rules?** Never in git/images/logs/front end; per-service least privilege; rotation; scanning; secret manager; if leaked, rotate first.

**H14. Container hardening flags?** Non-root, read-only filesystem + tmpfs, `cap_drop: ALL`, `no-new-privileges`, memory/PID limits, no published ports, no Docker socket, pinned minimal images.

**H15. What is a hash-chained audit log; what does it not prove?** Each entry hashes the previous; edits/mid-deletions break verification; it does not detect tail truncation or full rewrites without external anchoring of the head hash.

**H16. Why constant-time comparison?** `==` leaks how many bytes matched through timing; `hmac.compare_digest` does not.

**H17. XSS and React?** React escapes text by default; never render model/tool output as HTML; add CSP; sanitise Markdown.

**H18. Personal data in this app?** Email, password hash, conversation text (in checkpoints), IPs transiently; audit log stores no content; erasure must cover checkpoints, audit tags, backups, third parties.

## I. DevOps (Chapters 23-29)

**I1. Image vs container; VM vs container?** Image: layered template; container: running instance isolated by namespaces/cgroups sharing the host kernel; VMs have their own kernel.

**I2. Docker layer caching and ordering?** Instruction changes invalidate later layers; install dependencies (lockfile) before copying source.

**I3. Multi-stage builds?** Build in one stage, copy artefacts to a clean runtime stage: smaller, safer.

**I4. `ENV`/`ARG` for secrets?** Never: they persist in image metadata/history; inject at runtime or use BuildKit secret mounts.

**I5. `EXPOSE` vs publishing?** `EXPOSE` documents; `ports:` publishes to the host. Private services have no `ports:`.

**I6. Exec-form `CMD` and PID 1?** Direct execution so signals (SIGTERM) reach the process; shell form wraps in `sh -c`.

**I7. Container exits 137?** SIGKILL, often OOM; check `docker inspect` `OOMKilled` and memory limits.

**I8. `depends_on` guarantees?** Start order (and health with `condition`), not ongoing health.

**I9. Dev vs prod compose here?** Dev publishes DB/API and has an optional observability profile; prod publishes only Caddy, requires secrets (`:?`), adds web and Caddy.

**I10. Compose vs Kubernetes?** Compose: single host, simple; K8s: multi-node scheduling, self-healing, rolling updates, autoscaling, policy; map hardening flags to `securityContext`.

**I11. How does Caddy get certificates?** ACME (Let's Encrypt): needs DNS pointing to the server and ports 80/443; stores/renews in `/data`.

**I12. Rolling vs blue/green vs canary?** Gradual replacement; two full stacks with a switch; small traffic share for validation.

**I13. Build once, deploy many?** Promote the same image (tag = SHA) through environments so what was tested is what runs.

**I14. Test pyramid and flaky tests?** Many unit, fewer integration, few end-to-end plus evals; flaky tests are bugs: isolate time/randomness/network/order.

**I15. When to use a real DB in tests?** When SQL semantics (constraints, triggers, locks) matter; this repo creates a fresh migrated database per test.

**I16. Blameless postmortem contents?** Impact, timeline, root causes/contributing factors, detection and response, action items with owners.

**I17. Git: merge vs rebase vs squash; undo a pushed commit?** Merge preserves history, rebase linearises (never on shared commits), squash condenses; use `git revert` for pushed commits, `reset` only on local history.

**I18. You committed a secret. Steps?** Rotate/revoke, check usage, optionally rewrite history, add prevention (hooks, scanning, tests).

## J. System design (Chapters 30-32)

**J1. Framework for a design interview?** Clarify requirements, estimate, API/data model, high-level design, deep dives, bottlenecks/trade-offs, summary.

**J2. Scale a read-heavy service?** Cache (CDN, app, Redis), read replicas, indexes, denormalisation, async precomputation.

**J3. Cache invalidation strategies?** TTL, explicit invalidation on write, versioned keys, stale-while-revalidate; prevent stampede with single-flight/jitter.

**J4. CAP and PACELC?** During partitions choose consistency or availability; otherwise latency vs consistency.

**J5. Consistent hashing?** Ring with virtual nodes so adding/removing a node remaps ~1/N keys.

**J6. Rate limiter algorithms?** Fixed window, sliding log, sliding counter, token bucket, leaky bucket; distributed via Redis atomic ops.

**J7. What breaks if you run three API instances today?** In-memory limiters, login lockout, the active-turn lock; the MCP replay guard, credit ledger and caches (including `detail_refs`, causing buy-link failures).

**J8. How to fix the turn lock across instances?** Conditional DB lease (`busy_until`) or Redis `SET NX EX` with fencing.

**J9. Design an LLM gateway.** Unified API, routing, fallbacks, caching, per-team quotas, usage accounting, PII redaction, streaming pass-through, key custody; stateless instances with Redis/Postgres.

**J10. Design a long-running agent platform.** Queue + durable workflow with checkpoints, sandboxed tools, centralised budgets, progress events, cancellation, per-user concurrency, audit.

## K. Project deep-dive questions (Chapters 1, 1b, 8, 9, 11, 12, 20-22, 27, 32)

**K1. Walk me through the architecture.** Browser → Caddy (only public door) → web (UI) and api; api → Postgres (state), api → private MCP tool server (signed single-use tokens) → SerpAPI; api → OpenRouter. Evals/observability around it.

**K2. Why is `web` not talking to `api`?** The browser runs the UI and calls the API through Caddy on the same origin; the web container only serves files.

**K3. Which env file goes where, and why?** `.env.example` committed template; `.env` local root file read by compose, Python settings (walking parents) and scripts; `.env.production` created by two scripts and passed with `--env-file`; no env files in containers; each service receives only its listed variables.

**K4. Where do the JWT keys live?** Private keys only in the API, the MCP public key only in the MCP container; two separate pairs for user tokens and service tokens.

**K5. How does a conversation pause and resume?** `interrupt` in dedicated nodes, checkpoint in Postgres under the conversation id as thread id; the API detects the pending interrupt and resumes with `Command(resume=text)`.

**K6. How do you guarantee budget and men's-only results?** Clamp caps in code; verify every product with `verify_product`; require passing verification and total ≤ budget in `rank_and_validate`; evals gate it.

**K7. What does the verifier do when colour isn't stated?** Marks it `unknown + assumed`, accepts with `confidence: low`, ranks below confirmed, shows "Colour not confirmed"; contradictions are rejected.

**K8. What is weak in the verifier?** Keyword matching; colour words in brand names (e.g. a brand containing "Red") can falsely reject; low-confidence badge text names colour even when the item match was partial.

**K9. How is the tool server protected?** No public address, signed single-use tokens, Host/Origin checks, rate limits, credit caps, SSRF-hardened fetcher, fail-closed startup.

**K10. How do you know it works?** ~224 Python tests plus TS tests, including security and tamper tests; a 13-case eval with 8 gates and 4 soft signals; demo mode proves guarantees and plumbing only.

**K11. What would you change first?** Backups, CI, paid model, token/cost telemetry, then Redis for shared state; see the backlog in Chapter 32.

**K12. Why did you skip the Mastra gateway?** It added a hop and a second boundary without solving a problem; Mastra stayed for evals, tracing and audit.

**K13. How would you add try-on?** Async job pattern with object storage, moderation, strict privacy, provider adapter behind the tool server, per-user caps.

**K14. How would you deploy it?** Harden a VM, install Docker, generate keys on the server, fill `.env.production`, `up -d --build`, verify reachability and non-reachability, back up, monitor.

**K15. Tell me about a bug you found.** (Use the IPv6 stall, the cp1252 file wipe, the backslash-stripping heredocs, `BUY_LINKS` never incremented, or the `detail_refs` scaling coupling; explain symptom, diagnosis, fix, lesson.)

---

## L. Questions to ask *them*

* What does a typical customer engagement look like from first call to handoff? How long?
* What percentage of time is coding vs meetings vs travel?
* How do FDEs feed learnings back into the product? Examples?
* How is success measured for FDEs? How is quality (evals, security) treated?
* What does on-call or support load look like after deployments?
* What environments do customers deploy in (cloud, on-prem, air-gapped)?
* How are new FDEs onboarded and mentored?

## Exercises

1. Answer 20 random questions per day out loud; record the ones you stumbled on and re-study the chapters.
2. Turn the K-section into a 10-minute mock interview with a friend playing a sceptical engineer.
3. Write two more questions per section from your own confusion; answer them in your own words.
