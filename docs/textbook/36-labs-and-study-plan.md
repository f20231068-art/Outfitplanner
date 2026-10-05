# Chapter 36. Labs and a Study Plan

> **Learning objectives.** Turn reading into skill with hands-on labs mapped to every part of the book; complete capstone projects that build and extend a real system; follow a structured 12-week plan (with 4- and 8-week variants) that interleaves DSA, AI engineering, systems, security, DevOps, system design and interview practice; and self-assess honestly.
>
> **Prerequisites.** None. Start wherever you are weakest.

---

## 36.1 Ground rules for the labs

1. **Use demo mode and fakes first.** `BACKEND_MODE=demo` gives a free, deterministic stack. Spend real model/search credits only in labs that say so, and cap them.
2. **Never print or paste secrets.** List variable *names*; mask values; if a key appears in output, rotate it. Run `uv run pytest services/api/tests/test_repo_hygiene.py` before any commit.
3. **Predict before you run.** For each "break it" step, write your prediction; surprise is where learning happens.
4. **Work on a branch**; commit small; do not push unless you mean to.
5. **Keep a lab journal**: what you did, what happened, what you learned, what is still unclear.
6. **Write a test** for every bug you find.
7. **Time-box** (60-120 minutes per lab); stop and note blockers rather than spiralling.

Setup (once): Docker Desktop running; Python 3.12 + `uv`; Node 22+; clone the repo; `cp .env.example .env`; `uv run --project services/mcp python scripts/generate_jwt_keys.py`; `docker compose up -d postgres`; run all tests: `(cd services/api && uv run pytest -q)`, `(cd services/mcp && uv run pytest -q)`, `npm install && npm test -w apps/web && npm test -w apps/mastra`.

## 36.2 Labs by part

### Part II: Foundations and DSA

**Lab 1: References and copies (Ch. 2).** Reproduce the shared-list and mutable-default bugs; fix them. In `agent/graph.py`, remove the `dict(...)` copy in `gather_prefs` and write a test that shows what can go wrong with in-place mutation of state (hint: compare the checkpointed state before and after).

**Lab 2: Concurrency (Ch. 2).** Write a 100-thread counter with and without a lock. Then write an asyncio version that blocks the loop with `time.sleep` and observe latency of another task; fix with `asyncio.sleep`/`to_thread`.

**Lab 3: Data structures from scratch (Ch. 3).** Implement `TTLCache` variants: FIFO (as in the repo), LRU, LRU+TTL with a size bound. Write tests with a fake clock. Benchmark `x in list` vs `x in set` for 10⁶ items.

**Lab 4: Rate limiter shootout (Ch. 3-4, 30).** Implement fixed window, sliding log, token bucket. Replay the same synthetic request trace through each and plot accepted/rejected counts; explain the boundary burst of the fixed window.

**Lab 5: Algorithms (Ch. 4).** Implement every algorithm in Chapter 4 from memory in a scratch file with tests. Then solve three fresh problems per pattern (two pointers, sliding window, binary search, BFS/DFS, DP, heap).

**Lab 6: Property-based tests (Ch. 5, 29).** Add a Hypothesis test for `clamp_to_budget`; find the zero-cap corner; decide behaviour; fix test-first.

**Lab 7: Statistics (Ch. 5, 12).** Compute Wilson intervals for 13/13, 12/13, 45/50. Simulate 1,000 eval runs for a system with true pass rate 90% and show how often a 13-case run scores 13/13.

### Part III: AI engineering

**Lab 8: Tokens and cost (Ch. 6, 14).** Count tokens for the project's prompts and a sample conversation; build a cost calculator with configurable prices; compute cost per conversation and a monthly forecast.

**Lab 9: Sampling (Ch. 5-6).** Implement softmax with temperature; sample 10,000 tokens at several temperatures and plot frequencies. Call a real model ten times at temperature 0 and at 1 (small budget) and count distinct outputs.

**Lab 10: Structured output (Ch. 7).** Define a Pydantic schema for "interview question". Get a model (or a fake that sometimes misbehaves) to fill it via prompt-only, JSON mode and tool-calling. Add error-feedback retries to `structured()` and measure the improvement with the fake.

**Lab 11: Prompt iteration (Ch. 7, 12).** Create `plan_outfits.v3.md` (add a `reasoning` field); run the offline eval; compare variety and cost; decide keep/revert with evidence.

**Lab 12: Tools and MCP (Ch. 8).** Build a two-tool FastMCP server; call it with `Client`; read the schemas. Add a third tool to `services/mcp` with a provider seam; watch `test_tool_contract.py` fail until the contract is satisfied.

**Lab 13: Agent loop by hand (Ch. 9).** Implement the framework-free tool-calling loop (Section 9.9) against a fake model; add an iteration cap and a tool allow-list; test a runaway-loop case.

**Lab 14: LangGraph (Ch. 9).** Build the tiny interrupt graph; add a counter and a `print` before `interrupt` to observe re-execution; swap `MemorySaver` for `PostgresSaver` and prove a pause survives a restart.

**Lab 15: RAG (Ch. 10).** Build the minimal RAG over 30 Markdown files; create 20 questions with expected sources; measure recall@k; add BM25 + RRF; add a pgvector table with a tenant filter and a test that tenant A cannot retrieve tenant B's chunks.

**Lab 16: Verifier (Ch. 11).** Add the "Red Tape Men's Navy Shirt" test; predict the result; fix without breaking others; hand-label 50 products and compute precision/recall.

**Lab 17: Evals (Ch. 12).** Add three eval cases (non-English, absurd budget, injection attempt); write one deterministic and one judge-based scorer; calibrate the judge on 30 hand labels (κ or accuracy). Make a gate fail on purpose and watch the exit code.

**Lab 18: Observability (Ch. 13).** Increment `BUY_LINKS`; add token counters; wrap worker threads with `copy_context`; build a Grafana panel; write a Prometheus alert for credit exhaustion.

### Part IV: Stack

**Lab 19: Network forensics (Ch. 16).** With `curl -v` and DevTools, record a full register → chat → refresh sequence; annotate every header and cookie attribute. Break streaming with a buffering proxy (nginx default) and fix it.

**Lab 20: SQL and transactions (Ch. 17).** Practice the seven queries in 17.13. Reproduce a lost update in two `psql` sessions; fix with `FOR UPDATE` and with an atomic `UPDATE`. Write migration `002` adding `conversations.archived_at` + partial index, with a from-scratch migration test. Time `EXPLAIN ANALYZE` on 100k rows with and without the composite index.

**Lab 21: FastAPI service (Ch. 18).** Build the minimal service (Section 18.11), add JWT verification, a rate-limit dependency, a DB-backed `/me`, an SSE endpoint with `finally` cleanup, and `TestClient` tests including a cross-user 404.

**Lab 22: Front end (Ch. 19).** Add a Stop button with `AbortController`; add client-side URL scheme validation before opening the Buy tab; write React Testing Library tests.

### Part V: Security

**Lab 23: JWT by hand (Ch. 20).** Decode a real token manually; implement HS256 sign/verify from scratch; demonstrate algorithm confusion against a naive verifier and the fix with pinned algorithms.

**Lab 24: Auth hardening (Ch. 20).** Add TOTP MFA (enrolment, verification, recovery codes hashed) with migrations and tests; add a short reuse grace window to refresh rotation and test the two-tab race.

**Lab 25: SSRF and injection tests (Ch. 21).** Extend `check_link` tests with IPv4-mapped IPv6, decimal-encoded loopback, userinfo tricks and a fake resolver returning private addresses. Write a route-enumeration test that fails if a route lacks auth. Build a 20-case prompt-injection suite for a RAG prototype.

**Lab 26: Audit chain (Ch. 22).** Implement the 40-line chain; add anchoring and prove tail truncation is detected; tamper with the real `audit_log` as owner (disable trigger, edit, re-enable) and see `/admin/audit/verify` fail; implement an incremental verifier.

### Part VI: DevOps

**Lab 27: Linux (Ch. 23).** Produce a per-route request/error table from `docker compose logs api | jq`; write an idempotent `backup.sh` with `trap`; trigger the OOM killer in a small container and read exit code 137.

**Lab 28: Docker (Ch. 25).** Build the three images; record sizes; change one source line and see which layers rebuild; enable Next standalone output and shrink the web image; run the API with `--read-only` and fix the failure; scan with Trivy.

**Lab 29: Compose and wiring (Ch. 1b, 26).** Recreate the stack from an empty clone following Section 1b.6; print variable *names* in each container and compare to the matrix; break each connection on purpose and record the symptom; add a Redis service following the recipe.

**Lab 30: Deploy (Ch. 27).** Deploy the prod layout to a free-tier VM with an sslip.io name; harden SSH and the firewall; verify what must not be reachable; add log rotation and a nightly backup; document every deviation from `docs/deploy.md`.

**Lab 31: CI/CD (Ch. 28).** Add the GitHub Actions workflow; make a gate fail; add a scheduled live-eval job with a spend cap; write a blue/green cutover script on one VM.

### Part VII: System design

**Lab 32: Capacity (Ch. 30, 32).** Redo the capacity estimate with your own assumptions; run a Locust test in demo mode; find the first bottleneck; update the numbers.

**Lab 33: Scale-out (Ch. 32).** Implement Redis-backed limiters and the `busy_until` lease; make `detail_refs` shared; write a two-instance test proving limits, replay protection and buy links work across instances; run `docker compose up --scale api=2` behind Caddy and verify.

**Lab 34: Gateway (Ch. 31).** Build a tiny LLM gateway (FastAPI): exact cache, per-key rate limits, fallback between two fake providers, usage logging; load-test it.

## 36.3 Capstone projects

Pick at least one; each can anchor a portfolio piece and an interview story.

**Capstone A: A new domain from scratch (4-6 weeks).** Choose a domain (study planner, recipe planner, travel itinerary, interview coach, clinic scheduler). Fill the canvas (Chapter 34); build the skeleton in order (34.4); a LangGraph workflow with at least one interrupt; one private tool server with signed tokens; a deterministic verifier; an eval harness with gates and demo mode; auth and audit; Docker + Compose prod layout; CI; a deployed demo; README with threat model and honest limits.

**Capstone B: Scale this project (2-3 weeks).** Implement Chapter 32's Stages 1-3: backups, CI, token metrics, per-turn deadline, Redis shared state, DB lease, shared MCP caches, two API instances behind Caddy; load-test before/after; write the results.

**Capstone C: "Try it on me" (3-4 weeks).** Design (Chapter 31, Case 6) and build with a fake image provider first: async jobs, object storage (MinIO locally), moderation hook, signed URLs, deletion endpoint, privacy notes, threat model, eval cases; swap in a real provider behind the adapter if one is verified.

**Capstone D: Real-model quality (2 weeks).** Run the live eval suite within budget; build a taste judge (LLM + human labels, calibrated); produce a quality/cost/latency comparison of two models; recommend one with evidence.

## 36.4 The 12-week plan

**Assumptions:** 15-20 hours/week (about 2-3 hours on weekdays, 4-6 on weekends). Adapt by compressing (Section 36.5). **Each week:** read the chapters, do the labs, solve DSA problems, and end with a 30-minute out-loud review and a short written summary.

| Week | Theme | Read | Labs | DSA problems (target) | Output |
|---|---|---|---|---|---|
| **1** | Orientation + programming foundations | 1, 1b, 2 | 1, 2, run the stack (Lab 29 steps 1-5) | arrays/hashing: 8 | explain the architecture and one request end to end without notes |
| **2** | Data structures and algorithms I | 3, 4 (to 4.7) | 3, 4, 5 (part) | two pointers, sliding window, stack: 12 | implement LRU, rate limiters from memory |
| **3** | DSA II + math/stats | 4 (rest), 5 | 5 (rest), 6, 7 | binary search, trees, linked lists: 12 | 30 problems done total; Wilson CI explained |
| **4** | LLMs, prompting, structured output | 6, 7 | 8, 9, 10, 11 | graphs (BFS/DFS): 8 | cost calculator; structured-output comparison write-up |
| **5** | Tools, MCP, agents, LangGraph | 8, 9 | 12, 13, 14 | graphs/topological sort, heap: 8 | tiny interrupt graph; MCP server built |
| **6** | RAG, reliability, evals, observability | 10, 11, 12, 13 | 15, 16, 17, 18 | DP I: 8 | RAG with metrics; verifier precision/recall; eval gates |
| **7** | Cost/latency, vendors; networking and databases | 14, 15, 16, 17 | 19, 20 | DP II, backtracking: 8 | SQL practice done; network trace annotated |
| **8** | Backend, front end, security I | 18, 19, 20 | 21, 22, 23 | mixed review: 10 | FastAPI service; JWT by hand |
| **9** | Security II, integrity | 21, 22 | 24, 25, 26 | mixed review: 10 | threat model for the project; audit anchoring |
| **10** | DevOps | 23, 24, 25, 26, 27, 28, 29 | 27, 28, 29, 30, 31 | mock interviews (coding) x3 | deployed demo; CI running |
| **11** | System design | 30, 31, 32 | 32, 33, 34 | timed problems: 8 | 4 mock system designs (2 classic, 2 AI) out loud |
| **12** | Interviews and polish | 33, 34, 35, 37 | capstone polish | timed mocks x4 | pitch (30 s, 2 min, 10 min) recorded; 9 behavioural stories written; portfolio checklist complete |

**Total DSA:** ~100-120 problems with review, covering every pattern; re-solve the ones you missed after one week and one month.

### A typical study day

* 60-90 min: read a chapter section; stop and explain it aloud.
* 60-90 min: a lab or a coding session.
* 45 min: DSA problems (25 minutes stuck-time before looking at hints).
* 15 min: write the day's journal entry and flashcards (terms from the chapter's "Key terms").

### Weekly review ritual (30-45 minutes)

1. List what you can now explain without notes (aim for 5-10 items).
2. List what you could not explain (go back to the section).
3. Answer 15-20 questions from Chapter 35 for that week's topics.
4. Redo two DSA problems you missed.
5. Update the plan.

## 36.5 Variants

### 4-week intensive (if an interview is soon)

| Week | Focus |
|---|---|
| 1 | Chapters 1, 1b, 4 (all patterns, 40 problems), 30; project walkthrough pitch |
| 2 | Chapters 6-9, 11, 12 (AI core), question bank sections C-E; labs 10, 13, 14, 16, 17 |
| 3 | Chapters 16-18, 20-21, 25-27 (stack, security, deploy), question bank F-I; labs 20, 23, 25, 28, 29 |
| 4 | Chapters 31-33, 35; 6 mock interviews (2 coding, 2 design, 1 decomposition, 1 behavioural); polish stories; portfolio |

### 8-week (balanced)

Weeks 1-2: Part II; weeks 3-4: Part III; week 5: Part IV; week 6: Parts V-VI; week 7: Part VII; week 8: interviews and polish. Skip labs 21-22, 31, 34 if time is short, but do not skip evals, security or deployment labs.

### If you have a specific weak spot

* **DSA weak**: double the DSA allocation for weeks 2-7; do 3 timed problems daily.
* **AI weak**: weeks 4-6 first, then everything else.
* **DevOps weak**: do Labs 27-30 early; deploy something in week 3.
* **Communication weak**: record explanations weekly; do mock decomposition cases from week 5 on.

## 36.6 Self-assessment rubric

Score each area 0-3 every two weeks. **0** = unfamiliar, **1** = can follow explanations, **2** = can do it with references, **3** = can do it unaided *and* teach it. Target: 2+ everywhere and 3 in your strongest three areas by interview time.

| Area | 3 means you can... |
|---|---|
| Programming | explain references, concurrency, generators, error handling; spot races and blocking calls in code review |
| DSA | solve medium problems in 25-30 minutes in the pattern taxonomy, with complexity analysis |
| LLM fundamentals | explain tokens, attention, sampling, training stages, API statelessness; calculate cost |
| Prompting/structured output | design a schema + validators + retries + versioned prompts and justify each |
| Tools/MCP | design and secure a tool server; explain JSON-RPC lifecycle and auth |
| Agents/LangGraph | build a graph with interrupts and checkpoints; explain re-execution semantics |
| RAG | design ingestion and retrieval with ACLs and evaluation |
| Evals | build dataset, scorers, gates; explain statistics and judge calibration |
| Observability | instrument logs/metrics/traces; write PromQL; design alerts |
| Networking/web | trace a request end to end; debug CORS/cookies/TLS/streaming |
| Databases | design schema/indexes, explain isolation and locks, run safe migrations |
| Backend | structure a FastAPI service with DI, middleware, streaming and tests |
| Front end | build a streaming React UI with safe auth handling |
| Security | threat-model a system; explain JWT, Argon2, SSRF, injection, prompt injection |
| DevOps | write hardened Dockerfiles/compose; deploy with TLS; CI/CD pipeline |
| System design | run the framework; estimate capacity; justify trade-offs; scale this app in stages |
| Communication | give a clear 2-minute project pitch and handle a sceptical deep dive |

## 36.7 Progress tracker template

```
Week __   Dates: ______     Hours: __
Chapters read: ____        Labs done: ____        DSA solved: __ (new) / __ (reviewed)
I can now explain (without notes): 1) ...  2) ...  3) ...
Still fuzzy: 1) ...  2) ...
Bug of the week (symptom -> cause -> fix -> test): ...
Mock interview feedback: ...
Next week's priorities: ...
Rubric changes: Programming 2->2, DSA 1->2, ...
```

## 36.8 After the plan

* **Ship and share**: deploy the demo, record the walkthrough, publish the write-up, tidy the README.
* **Keep a weekly cadence**: one new DSA topic, one new AI/infra experiment, one blog note.
* **Stay current**: model releases, framework changelogs (read them, run your evals), security advisories.
* **Teach**: explain a chapter to someone else; teaching reveals gaps.
* **Contribute**: fix a bug or docs in a tool you use.
* **Reflect each quarter**: what you can build now that you could not three months ago.

## Common mistakes

* Reading without doing: the labs are the learning.
* Spending only on DSA or only on AI; the role needs both, plus communication.
* Skipping measurement (evals, load tests) and deployment.
* Copying solutions instead of struggling first.
* Not practising out loud.
* Burning real credits or leaking secrets during experiments.

## Summary

* Labs convert chapters into skills; each has a prediction step and a test.
* Four capstones (new domain, scale-out, try-on, real-model quality) produce portfolio-grade work.
* A 12-week plan interleaves reading, labs, DSA and mocks; 4- and 8-week variants compress it.
* Self-assess with the rubric and review weekly; keep shipping and teaching after the plan ends.

## Exercises

1. Choose your plan variant and put the first four weeks on a calendar today.
2. Complete the rubric honestly and pick your three weakest areas to front-load.
3. Do Lab 29 end to end; you will learn more about this project's wiring from breaking it than from reading it.
