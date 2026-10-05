# Chapter 31. Designing AI Systems (with Worked Cases)

> **Learning objectives.** Explain what makes AI systems different to design; use a reference architecture and a catalogue of AI-specific patterns (gateway, caching, routing, RAG, agents, async jobs, guardrails, evaluation pipelines, human review); decide whether and how much autonomy to give a model; and work through six full design cases (document Q&A, support copilot, LLM gateway, long-running agent platform, document-processing pipeline, virtual try-on) in the style of an interview or a customer workshop.
>
> **Prerequisites.** Chapters 6-15, 30.

---

## 31.1 What is different about AI system design

| Property | Consequence for design |
|---|---|
| **Non-deterministic outputs** | validation, verification, retries, evals instead of "it passed once" |
| **High per-request cost and latency** (seconds, real money) | caching, streaming, routing, budgets, async patterns, rate limits |
| **Quality is statistical and subjective** | an evaluation pipeline is part of the system, with datasets and metrics |
| **Capabilities change monthly** (models, prices, APIs) | abstraction seams, pinned versions, fallbacks, cheap model swaps |
| **Untrusted text is instructions** (prompt injection) | least privilege, no lethal trifecta, sanitised output, human confirmation |
| **Data governance** (user text sent to third parties) | residency, retention, redaction, DPAs, tenant isolation |
| **External dependencies dominate failure and cost** | timeouts, circuit breakers, graceful degradation, vendor-quota planning |
| **Users need trust cues** | citations, confidence, honest uncertainty, undo, human escalation |
| **Feedback is a resource** | log traces, collect signals, build datasets from production |

The ordinary system-design toolkit (Chapter 30) still applies; AI adds the rows above.

## 31.2 A reference architecture

```
 Clients (web, mobile, API, Slack...)
      │  HTTPS, auth, streaming (SSE/WebSocket)
      ▼
 Edge: CDN / WAF / reverse proxy / rate limiting                       ← Caddy here
      ▼
 Application API  (authn/z, sessions, quotas, validation, audit)        ← FastAPI routes
      ▼
 Orchestrator  (workflow/agent: prompts, state machine, HITL, budgets)  ← LangGraph graph
      │            │                   │                  │
      ▼            ▼                   ▼                  ▼
 Model gateway   Tools layer        Retrieval/data      State & memory
 (routing,       (private services, (vector/search/     (checkpoints, user
  fallback,       MCP, internal      SQL, ACL-filtered) profile, history)   ← Postgres
  cache, limits,  APIs, sandboxes)
  usage logging)  ← MCP server here
      │
      ▼
 Model providers (hosted APIs, self-hosted open models)                 ← OpenRouter here
 
 Cross-cutting: guardrails/verifiers · async workers/queues · observability (logs/metrics/traces) ·
                evaluation pipeline & datasets · prompt/model/schema registry · secrets & identity · cost controls
```

Mapping to this repo: edge = Caddy; app API = `routes/*`; orchestrator = LangGraph graph; model access = `get_llm` (a thin gateway: the seam, no caching or routing yet); tools = the private MCP server; retrieval = SerpAPI search + verifier (no vector store); state = Postgres checkpoints + app tables; guardrails = verifier and clamps; observability and evals = Prometheus/Grafana/Jaeger + Mastra; registry = versioned prompt files; cost controls = rate limits and credit ledgers.

## 31.3 Pattern catalogue

### Model gateway / LLM proxy

A service (LiteLLM, Portkey, Cloudflare AI Gateway, OpenRouter, or your own) between applications and providers that provides: **one API** for many models, **routing** (cheap vs strong model, by task or tenant), **fallbacks** across providers on error or rate limit, **retries with backoff**, **caching** (exact and semantic), **rate limits and budgets per team/key/user**, **usage and cost logging** (tokens, latency), **PII redaction** and policy enforcement, **secrets isolation** (applications never hold provider keys), **A/B and canary** routing, **audit**. This is the first platform component to build when several teams use LLMs. *In this repo `get_llm` plus the `InstrumentedLLM` wrapper is a minimal in-process gateway; a standalone one would centralise limits and key custody.*

### Caching layers

* **Exact-match response cache**: key = hash of (model, prompt, parameters); only safe for deterministic, non-personalised calls.
* **Semantic cache**: embed the query; if a stored query is within a similarity threshold, return its answer. Fast and cheap; **risks wrong reuse**; partition by tenant/user and use high thresholds; never for personalised or time-sensitive answers.
* **Provider prompt (prefix) caching**: structure prompts with stable prefixes (Chapter 14).
* **Tool/result caches**: the MCP server's search cache.
* **Embedding caches**: for repeated texts.

### Routing and cascades

Send each request to the cheapest model likely to succeed; escalate on low confidence (a verifier or self-check fails). Routing signals: task type, input length, language, user tier, sensitivity (route PII to a private model). Measure with evals; keep the routing rule simple.

### Retrieval-augmented generation

Chapter 10: ingestion pipeline, hybrid retrieval, reranking, ACL filtering at query time, citations, groundedness checks, evaluation of retrieval and generation separately.

### Agents with tools

Chapters 8-9: bounded loops, least-privilege tools, human approval for risky actions, tracing every step, budgets.

### Durable workflows and human-in-the-loop

State machine with checkpoints (LangGraph, Temporal, Step Functions): pause for approval, resume days later, retry steps, audit each decision. Use when a process spans minutes to days or involves humans.

### Async job pattern for long tasks

For anything slower than a few seconds (image generation, long research, batch extraction): `POST /jobs` returns `202 Accepted` + `job_id`; a **queue** and **workers** do the work; the client **polls** `GET /jobs/{id}` or listens via SSE/WebSocket/webhook; results stored in object storage/DB; **idempotency key** for retries; **timeouts and cancellation**; **progress events**; **dead-letter queue**; **quotas** per user.

### Guardrails and verification

Input filters (size, PII, topic), constrained outputs (schemas), deterministic verifiers (Chapter 11), moderation, output sanitisation, link allow-lists, human review queues for low-confidence outputs, kill switches.

### Human review queue

Route low-confidence or high-stakes outputs to a person; capture the correction as **training/eval data**; measure the review rate (a cost) and error escape rate (a risk). This is how automation ratio increases safely over time.

### Evaluation and feedback pipeline

Offline datasets in git, CI gates, scheduled live evals, production sampling, LLM-judge calibrated on human labels, dashboards, alerts on drift, a path from a failed production trace to a new test case (Chapter 12).

### Registry and release management

Prompts, schemas, model choices, tool definitions and eval datasets are **versioned artefacts**; deployments reference versions; canary and rollback by version pin (Chapter 28).

### Multi-tenancy

Isolate **data** (tenant-filtered retrieval, row-level security, per-tenant indexes or namespaces), **cost** (per-tenant budgets), **rate limits**, **configuration** (prompts, models, tools), **logs** (access control), and **caches** (keys include tenant id). Cross-tenant leakage is the catastrophic AI failure.

## 31.4 Should this be AI at all? How much autonomy?

Decision questions:

1. **Can rules, SQL or search solve it?** (Often yes for the structured parts; use the model for language understanding, generation, and fuzzy judgement.) *The best AI systems are hybrid: AI Stylist uses a model for intent and planning, search for facts, code for verification and arithmetic.*
2. **What is the cost of an error?** Low (a wrong style suggestion) → more autonomy. High (money, health, legal, irreversible actions) → human approval, narrow tools, strong verification.
3. **Can errors be detected?** If you can verify automatically (code tests, rules, schema), autonomy is safer.
4. **Is there ground truth to evaluate against?** If not, invest in human review first.
5. **Value vs cost/latency**: does the improvement justify seconds of latency and cents per request?

**Autonomy ladder**: (1) *suggest only* (a human decides everything) → (2) *draft and the human edits/approves* → (3) *act with confirmation for risky steps* → (4) *act autonomously within tight guardrails with monitoring* → (5) *fully autonomous* (rare, with strict limits). Start at 1-2, move up as evals and incident history earn it.

## 31.5 Worked cases

For each: requirements, scale, architecture, deep dive, failure modes, evals, cost and security. Practise speaking each in 10-15 minutes.

---

### Case 1: Enterprise document Q&A over 10,000 PDFs (RAG)

**Requirements.** Employees ask questions; answers must cite sources; users may only see documents they have access to; ~500 employees; answers in < 10 s; documents change weekly; no data leaves the company's cloud region.

**Estimates.** 10,000 PDFs × ~30 pages ≈ 300,000 pages ≈ ~150M tokens ≈ ~400k chunks of ~400 tokens. Embeddings: one-time ~150M tokens (cheap); storage: 400k × 1,536 floats × 4 bytes ≈ 2.4 GB (fits in pgvector/HNSW memory). Queries: 500 users × 10/day = 5,000/day (0.06/s average): trivial load; cost dominated by generation (~3k input tokens each).

**Architecture.**

```
Ingestion: connectors (SharePoint/Drive/S3) → parser (layout-aware, OCR) → chunker (structure-aware, overlap)
           → metadata (doc id, version, ACL groups, dates) → embed → Postgres (pgvector HNSW + tsvector) ; raw files in object storage
Query:     user (SSO) → API → query rewrite → hybrid retrieval (vector + BM25) WITH ACL filter → rerank → prompt assembly
           → LLM (cite ids, "answer only from context") → citation/groundedness check → stream answer + source links
Ops:       incremental re-indexing (CDC/webhooks), deletion propagation, eval pipeline, tracing, feedback buttons
```

**Deep dives.** (1) **Access control**: store each chunk's ACL; filter in the retrieval query by the *user's* groups from the IdP; never rely on the model to hide content; cache keys include user/groups. (2) **Chunking** by headings/tables; parent-child retrieval. (3) **Evaluation**: 150 real questions with expected sources; recall@5/10, faithfulness, refusal correctness; run on every ingestion or prompt change. (4) **Freshness/deletion**: versioned documents; deleted/changed source removes old chunks and invalidates caches. (5) **Prompt injection**: documents may contain instructions; delimit, and the model has no powerful tools.

**Failure modes.** Parsing garbage (tables/scans) → bad retrieval; stale index; wrong-ACL leak; confident wrong answers when retrieval fails (mitigate with a similarity threshold and "I could not find that"); cost spikes from huge contexts.

**Metrics.** Answer acceptance (thumbs), citation-click rate, no-answer rate, p95 latency, cost per answer, retrieval recall on the eval set.

---

### Case 2: Customer-support copilot with tools (orders, refunds)

**Requirements.** Chat assistant for an e-commerce site; answers policy questions (RAG) and performs actions: check order status (read-only), start a return, and **issue a refund** (money!). 20,000 chats/day; p95 first token < 3 s; must never refund wrongly; escalate to humans.

**Architecture.**

```
Customer ─► Chat gateway (auth: the customer's session) ─► Orchestrator (workflow)
   intent router (small model) ─► policy Q&A (RAG) | order lookup tool | returns tool | refund workflow | human handoff
Tools (private service, per-customer scoped tokens): get_order(order_id), list_orders(), start_return(order_id, reason),
   propose_refund(order_id, amount)  ← creates a PENDING refund, never executes
Refund workflow: propose → deterministic policy engine checks (within window? amount ≤ order? fraud score?) →
   auto-approve if low risk (< threshold) else human queue → execute via payments API with an IDEMPOTENCY KEY → audit
```

**Deep dives.** (1) **Least privilege and identity propagation**: tools receive the *authenticated customer id*, never a customer id from the model's arguments; every tool re-checks ownership (the confused-deputy defence; this repo's per-user token subject). (2) **Action safety**: the model can only *propose*; a deterministic policy engine and, above a threshold, a human approve; exact amounts and order ids shown to the approver, not the model's prose summary. (3) **Idempotency**: retried refund calls must not double-pay (idempotency keys, unique constraints). (4) **Prompt injection**: order notes, product names and customer text are untrusted; tool outputs delimited; no tool that sends email/links to arbitrary destinations; PII redaction in logs. (5) **Latency**: stream tokens; small model for routing; cache policy documents' retrieval; parallel tool calls. (6) **Escalation**: low confidence, repeated misunderstanding, anger detection, explicit request → human with full context.

**Failure modes.** Wrong refund (mitigated by policy engine + approvals), looping agent (iteration cap), tool outage (graceful message + handoff), hallucinated policy (RAG + citations + verifier), abuse (rate limits, per-customer refund caps).

**Evals.** Scenario suites (200 dialogues) with expected tool calls and outcomes; **red-team** injection attempts; shadow mode before launch (agent drafts, humans send), then partial automation; track containment rate, CSAT, error escape rate.

---

### Case 3: An internal LLM gateway and platform for 30 teams

**Requirements.** Central service so teams call models safely and cheaply: unified API, provider failover, per-team budgets, usage dashboards, PII redaction, prompt/response logging with retention controls, no provider keys in apps, ~200 requests/s peak, p99 added latency < 50 ms.

**Architecture.**

```
Apps ─► Gateway (stateless, N instances behind LB, OpenAI-compatible API)
   authn (service tokens/OIDC) → quota check (Redis) → request normalisation → policy (PII redaction, allowed models per team)
   → cache lookup (exact; semantic optional) → router (model selection, fallback chain) → provider adapters (retries, timeouts, circuit breakers)
   → streaming passthrough → usage accounting (async: tokens, cost, latency) → response filters
Control plane: team/key management, budgets, model catalogue & prices, routing rules (config as code), dashboards
Data plane stores: Redis (rate limits, caches), Postgres (config, usage rollups), object storage/ClickHouse (logs, with retention & access control)
```

**Deep dives.** (1) **Streaming proxying** without buffering; handling client disconnects (cancel upstream to stop paying); SSE format translation between providers. (2) **Rate limiting** by tokens-per-minute and requests-per-minute using a shared store; fail-open vs fail-closed policy. (3) **Fallback logic**: errors (429/5xx/timeouts) → next provider/model; avoid retry storms; idempotency for non-streaming; circuit breakers per provider; consistency of **features** across models (tool calling, JSON schema) via capability metadata. (4) **Cost accounting**: count tokens from provider `usage`; reconcile with invoices; async pipeline so the hot path stays fast. (5) **Security**: keys in a secret manager, per-team scoping, **log redaction**, tenant isolation of cache keys, audit of admin actions. (6) **Latency budget**: the gateway must add milliseconds, so keep it lean (async I/O, no heavy synchronous logging).

**Failure modes.** Gateway outage (single point of failure → multi-AZ, health checks, client-side fallback to direct provider in emergencies), Redis outage (degrade limits), provider-wide incident (failover), cost runaway by a buggy team (budgets with hard cutoffs and alerts), PII in logs (redaction before logging, short retention).

---

### Case 4: A long-running research/agent platform

**Requirements.** Users submit "research X and write a report" tasks taking 5-30 minutes, calling search/browse/code tools; tasks must survive restarts, show progress, be cancellable, have cost caps, and produce an auditable trail.

**Architecture.**

```
Client ─► API ─► POST /tasks (202) ─► tasks table + queue
Workers (autoscaled) pull tasks → run agent loop in a durable workflow (checkpoint per step; Temporal/LangGraph+Postgres)
   tools in SANDBOXES (egress-restricted containers; SSRF-guarded fetchers; no secrets in env)
   budgets enforced centrally: max steps, max tokens, max tool calls, max wall-clock, max cost
Progress: events table → SSE/WebSocket/polling ; artifacts (report, sources) → object storage
Observability: per-task trace; step log (inputs/outputs fingerprints); cost per task ; audit
```

**Deep dives.** (1) **Durability**: each step persisted; on worker crash another resumes from the checkpoint (idempotent tools or recorded results); heartbeats and visibility timeouts. (2) **Budgets as a first-class guard**: a central "budget manager" tracks tokens/cost per task and *stops* the loop gracefully, producing a partial report. (3) **Context management**: summarise/clear old tool results; store raw documents externally and keep references. (4) **Sandboxing and SSRF**: browse tools run with egress allow-lists, DNS-pinned fetchers (Chapter 21), no access to internal metadata services, resource limits; code execution in isolated micro-VMs/containers. (5) **Prompt injection**: pages are hostile; the browsing agent has *no* powerful tools or private data (break the lethal trifecta); results are passed as structured, sanitised summaries to the planning model. (6) **Cancellation and idempotency**. (7) **Fairness**: per-user concurrency limits, priority queues. (8) **Evaluation**: task-level rubrics with LLM judges calibrated by humans, citation verification (does the cited page support the claim?).

**Failure modes.** Runaway loops (caps), stuck tasks (heartbeats, timeouts), poisoned sources (verification, source reputation lists), rising cost (budgets, per-user quotas), flaky tools (retry with backoff, alternative tools).

---

### Case 5: Document-processing pipeline (invoices to structured data)

**Requirements.** Ingest 200,000 invoices/day (PDF/images), extract fields (vendor, date, line items, totals), validate, and load into an ERP; accuracy ≥ 98% on key fields; humans review uncertain cases; audit trail.

**Architecture.**

```
Upload/email → object storage → queue → [OCR/vision parse] → [LLM extraction → JSON schema] → deterministic validators
   (totals = sum of lines? dates valid? vendor in master data? currency?) → confidence score
   → high confidence: auto-post to ERP (idempotent by invoice id) ; low/failed validation: human review queue (UI shows doc + extracted fields)
   → corrections stored as labelled data → weekly eval + fine-tuning/prompt updates ; dashboards; audit
```

**Estimates.** 200k/day ≈ 2.3/s average, ~10/s peak; each document = ~1-2 model calls with images (seconds): throughput needs **parallel workers and queues** rather than synchronous requests; use **batch APIs** for non-urgent backlog (about half price) and real-time for priority.

**Deep dives.** (1) **Schema-constrained extraction** + **business-rule validators** (arithmetic checks catch hallucinated numbers: *the model proposes, code disposes*). (2) **Confidence and routing**: combine model-provided signals, validator results and field-level checks to decide auto vs human. (3) **Human-in-the-loop UX**: fast review tool, keyboard shortcuts, highlight evidence regions. (4) **Idempotency/duplicates**: invoice hash and business keys; exactly-once effect into the ERP. (5) **Privacy/compliance**: PII/financial data, retention, region, vendor DPAs. (6) **Evaluation**: field-level precision/recall on a labelled set, drift monitoring per vendor layout, regression suite from corrections. (7) **Cost**: choose OCR+small model vs vision model per document class; cache by document hash.

**Failure modes.** Layout drift, language variants, poisoned PDFs (embedded instructions: schema and validators bound the damage), duplicate postings, queue backlog (autoscale, DLQ).

---

### Case 6: Virtual try-on for AI Stylist ("try it on me"), the unbuilt feature

**Context.** The README lists "Try it on me" (photos, character sheet, try-on images) as **not built: waiting on a decision about the image provider**; `docs/tools-reference.html` sketches tools `generate_image`, `create_character_sheet`, `generate_tryon`, `get_job`. Designing it is a realistic extension and a strong interview story.

**Requirements.** A user uploads a photo; the system creates a private "character sheet" and renders each outfit on them; results in < 60 s with progress; strict privacy (biometric-like data); abuse prevention (no nudity/minors/deepfakes of others); cost caps.

**Architecture.**

```
Browser ─► POST /tryon/uploads (signed URL → object storage, size/type limits, malware/EXIF scrub, moderation)
        ─► POST /tryon/jobs {outfit_id}  → 202 {job_id}   (ownership check: the outfit belongs to this user)
API ─► jobs table + queue ─► worker ─► MCP tool server: create_character_sheet / generate_tryon (image provider adapter, 1 file)
        provider call (async, polled) → result image → moderation check → object storage (private bucket, short-lived signed URLs)
Client: poll GET /tryon/jobs/{id} or SSE progress ; images displayed via signed URLs ; "delete my photos" endpoint
```

**Deep dives.** (1) **Async job pattern** (the image provider takes tens of seconds and is rate limited): job table, `FOR UPDATE SKIP LOCKED` worker, idempotency, retries, per-user concurrency 1-2, global concurrency to respect provider limits. (2) **Provider adapter seam** (`providers/<name>.py`) so the choice is swappable; contract-test with recorded responses; **verify the model's actual capabilities before building** (the project's notes record that the proposed model name could not be verified: *never build on an unverified vendor claim*). (3) **Privacy**: explicit consent, purpose limitation, private storage, encryption, short retention, deletion endpoint that also removes derived images and backups per policy, no training on user photos by the provider (check terms), region (India DPDP Act: consent, notice, children), strip EXIF/location. (4) **Safety**: age/NSFW/face-of-someone-else checks, prompt constraints, output moderation, rate limits, audit (job created, deleted). (5) **Cost model**: image generation is far costlier than text; per-user daily caps, global budget, caching of the character sheet. (6) **Security**: signed URLs scoped and short-lived; uploads validated (type sniffing, size limits, image re-encoding to neutralise payloads); SSRF-safe handling of any URL inputs; ownership checks on every job/image. (7) **UX**: progress, honest "this is an AI rendering, not exact fit", easy deletion.

**Failure modes.** Provider outage or quota (queue, retry, graceful message), inappropriate content (moderation, review queue), privacy incident (minimise retention, access logs, encryption), cost explosion (caps, alerts).

---

## 31.6 Answering AI system design questions in an interview

A structure that works:

1. **Clarify**: users, task, quality bar, scale, latency, data sensitivity, error cost.
2. **Decide the AI role**: where the model adds value; what stays deterministic.
3. **Draw the architecture** using the reference layers; name each component's job.
4. **Walk one request end to end** with data and latency.
5. **Deep-dive** on what matters: retrieval and ACLs, tool safety, async jobs, caching, routing, evals.
6. **Quality**: how you measure (dataset, metrics, judge, human review) and improve (feedback loop).
7. **Reliability**: timeouts, retries, fallbacks, degradation, budgets.
8. **Security and privacy**: injection, least privilege, tenancy, retention.
9. **Cost and latency**: estimates and levers.
10. **Evolution**: MVP → scale; what you would monitor; what you would build next.

Frequent follow-up questions: *How do you reduce hallucinations? How do you evaluate it? What if the provider is down or rate limits you? How do you control cost? How do you prevent prompt injection? How do you handle PII? How would this scale 100×? How do you roll out a new prompt or model safely?* You already have answers to all of these from this book and this repo.

## 31.7 Anti-patterns

* **Model as database or calculator.**
* **Autonomous agent where a workflow suffices.**
* **No eval, no baseline**, just demos.
* **Unbounded loops/spend.**
* **Giving the model write access and untrusted input at once.**
* **Direct provider calls scattered everywhere** (no gateway/seam).
* **Caching personalised answers under shared keys.**
* **Treating the vector DB as the whole system** (retrieval quality, ACLs, freshness, evaluation are the work).
* **Synchronous requests for minutes-long work.**
* **Ignoring data residency and retention**.
* **Big-bang model swaps without evals.**

## Common mistakes

* Designing the happy path only.
* Forgetting multi-tenant isolation.
* Not budgeting for evals and human review.
* Skipping the async pattern for long tasks.
* Underestimating third-party quota and cost as the real bottleneck.

## Summary

* AI systems add non-determinism, cost, evaluation, injection risk and governance to ordinary design concerns.
* A reference architecture: edge → API → orchestrator → {model gateway, tools, retrieval, state} with guardrails, async workers, observability, evals and registries across the top.
* Key patterns: gateway, caching, routing, RAG, tool agents, durable workflows, async jobs, guardrails, human review, eval pipelines, versioned artefacts, tenancy.
* Choose autonomy by error cost and verifiability; start with suggestion and approval.
* Six cases demonstrate the method; try-on shows how to extend this project responsibly.

## Key terms

*model gateway, semantic cache, router/cascade, RAG, durable workflow, async job (202 + poll), guardrail, human review queue, autonomy ladder, idempotency key, multi-tenancy, ACL filter, budget manager, sandbox, signed URL, shadow mode.*

## Interview questions

1. Design an enterprise document Q&A system with per-user permissions.
2. Design a support agent that can issue refunds safely.
3. Design an LLM gateway for many teams: what features and failure modes?
4. How would you build a 20-minute research agent that survives restarts and stays within budget?
5. How would you add a "try it on me" feature to this app? What are the privacy and safety issues?
6. When would you not use an LLM?
7. How do you decide how much autonomy to give an AI feature?

## Exercises

1. Pick one case, write a one-page design (requirements, estimates, diagram, three deep dives, risks), and present it in 10 minutes to a friend.
2. Implement a tiny LLM gateway (FastAPI) with exact caching, per-key rate limits, fallback between two providers (fake ones), and usage logging; load-test it in demo mode.
3. Implement the async job pattern in this repo for a fake "slow task" with `FOR UPDATE SKIP LOCKED`, status polling and tests.
4. Write the threat model for Case 2's refund workflow (assets, attackers, abuse cases, controls).
5. Redesign AI Stylist for 1,000 concurrent users using this chapter's patterns; list changes in priority order.
