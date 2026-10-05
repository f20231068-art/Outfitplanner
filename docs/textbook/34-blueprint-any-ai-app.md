# Chapter 34. The Blueprint: Building Any AI Product

> **Learning objectives.** Take any AI product idea from a sentence to a deployed, evaluated, secure service using a repeatable lifecycle; fill in a one-page canvas; use decision trees (AI or not, workflow or agent, RAG or fine-tune, sync or async, where to host); start every project from the same skeleton; run the production-readiness checklists; and map the pattern onto other kinds of AI product.
>
> **Prerequisites.** The whole book; this chapter is its distillation. Use it as the document you open at the start of a new project.

---

## 34.1 The lifecycle (the order this project was built in, generalised)

```
1 Frame  →  2 Validate  →  3 Design  →  4 Walking skeleton  →  5 Make it correct  →  6 Make it safe
   →  7 Make it persistent & visible  →  8 Deploy  →  9 Operate  →  10 Improve (loop 4-9)
```

### 1. Frame the problem (hours)

Write one paragraph: **who** has **what problem**, what they do today, what "better" means **in numbers**, and what is **out of scope**. If you cannot state the success metric, you are not ready to build.

*Deliverable:* the one-page canvas (Section 34.2).

### 2. Validate cheaply (days)

* Can the core task be done by a model **on 10-20 real examples**? (A notebook, no code structure.)
* Do you have, or can you get, the **data and access**?
* Is there a **non-AI** approach that is good enough?
* Who can **block** the project (security, legal, IT)? Ask them now.

*Deliverable:* a go/no-go note with evidence, risks and the smallest viable slice.

### 3. Design (1-3 days)

Choose: **AI role** (what the model decides vs what code decides), **workflow vs agent** (Chapter 9), **tools and data sources** (Chapters 8, 10), **autonomy level** (Chapter 31), **state and storage** (Chapter 17), **hosting** (Chapters 26-27), **evaluation plan** (Chapter 12), **threat model** (Chapter 21), **cost model** (Chapter 14). Write a short architecture note and **decision records** for non-obvious choices.

*Deliverable:* architecture diagram, data model sketch, risks, and the **eval plan** (the dataset you will build and the gates).

### 4. Walking skeleton (days)

Build the thinnest **end-to-end** slice with **fakes at every edge**: a scripted model, mock tools, an in-memory or throwaway DB, a trivial UI or CLI. The point is to prove the **flow and the seams**, and to have something demonstrable, fast. (This project's first milestone: an agent with a mock search and a mock model.)

*Deliverable:* one user journey runs end to end offline; tests pass; CI exists.

### 5. Make it correct (the core of the work)

Replace fakes with real components **one at a time**, each behind a seam:

* real model (structured output, validation, retries) → Chapter 7
* real tool/data source (adapter + recorded fixtures) → Chapters 8, 15
* **deterministic verification and enforcement** of every promise (Chapter 11)
* the **eval harness** with gates (Chapter 12)

*Deliverable:* eval scorecard on real data; verifier; adapters with fixtures.

### 6. Make it safe

Authentication and **object-level authorisation**; input validation; **secrets management**; rate limits and **spend caps**; SSRF/injection defences; prompt-injection design; privacy and retention decisions; audit trail; hardened containers (Chapters 20-22, 25).

*Deliverable:* threat model reviewed; security tests; residual-risk register.

### 7. Make it persistent and visible

Database with migrations; durable agent state; **structured logs, metrics, traces, dashboards, alerts**; cost and token telemetry; feedback capture (Chapters 13, 17).

*Deliverable:* you can answer "what happened in this request?" and "how is it doing overall?".

### 8. Deploy

CI/CD, container images by SHA, environment configuration (Chapter 1b), one public door, TLS, backups, rollback plan, runbook (Chapters 26-28).

*Deliverable:* reproducible deployment from a clean machine, verified including what must **not** be reachable.

### 9. Operate

SLOs, alerts, on-call, incident process, cost watching, dependency updates, model/provider change management, regular restore drills.

### 10. Improve

Production traces and feedback → new eval cases → prompt/model/retrieval changes → evals → canary → release. Repeat.

## 34.2 The one-page canvas

Copy this into the top of your repo's `docs/` and fill it in before writing code.

```
PROJECT:                                   OWNER:                         DATE:

1. PROBLEM       Who suffers? What do they do today? Cost of the problem (time, money, risk)?
2. USERS         Primary / secondary / admins / stakeholders / blockers
3. VALUE         What changes for them? Success metric(s) with a target and how we measure it
4. SCOPE         In scope (MVP):                     Out of scope (explicit):
5. AI ROLE       What the model does (understand, plan, generate, classify...):
                 What code/rules do (verify, compute, enforce, route):
6. AUTONOMY      suggest / draft+approve / act-with-confirmation / autonomous (circle one) — why?
7. DATA          Sources, owners, sensitivity, freshness, volume, quality, access method, retention
8. TOOLS         External systems/APIs, read vs write, credentials, rate limits, costs
9. ARCHITECTURE  Diagram link; servers; trust boundaries; state stores; sync vs async
10. QUALITY      Eval dataset (source, size), scorers, gates vs soft signals, human review plan
11. RISKS        Top 5 (technical, security, privacy, cost, adoption) + mitigations
12. CONSTRAINTS  Compliance, residency, approved vendors/models, network, budget, deadline
13. COST MODEL   Per request (tokens, tool credits, infra) x volume; caps; kill switch
14. ROLLOUT      Shadow → pilot → partial → full; rollback; owner of on-call
15. OPEN QUESTIONS / ASSUMPTIONS
```

## 34.3 Decision trees

### Should this use an LLM at all?

```
Can deterministic rules/SQL/search solve it reliably?  ── yes ─► do that (add an LLM only for language I/O)
 └ no: does it need language understanding, generation, or fuzzy judgement?  ── no ─► classical ML / rules
    └ yes: is an error cheap/detectable (verifier, human review)?  ── no ─► human-in-the-loop, narrow scope, or don't automate
       └ yes ─► LLM, with verification and evals
```

### Workflow or agent?

```
Do you know the steps in advance?  ── yes ─► WORKFLOW (code decides order; model fills steps)
 └ no: is the task open-ended with unpredictable tool use, and are errors recoverable and cost bounded?
      ── no ─► workflow with a few model-chosen branches + hard caps
      └ yes ─► AGENT, with budgets (steps/tokens/time/money), least-privilege tools, tracing, approvals for risky actions
```

### Knowledge: prompt, RAG, fine-tune?

```
Small, stable knowledge? ─► put it in the prompt (cache it)
Large/changing/private documents or need citations/permissions? ─► RAG (hybrid + rerank + ACL)
Need a consistent style/format/narrow behaviour at high volume, prompting insufficient? ─► fine-tune (after evals show the gap)
Need exact facts/computation? ─► tools/code, not the model's memory
```

### Sync, streamed, or async job?

```
Answer in < 2 s?  ─► plain request/response
2-60 s and user is waiting? ─► stream progress (SSE), show partial results
> 1 minute, expensive, or rate-limited provider? ─► async job: 202 + job id + queue + workers + status/SSE/webhook
```

### Model choice

Define quality bar on your eval → shortlist models meeting constraints (privacy, latency, context, tools) → measure quality/latency/cost → pick the cheapest that clears the bar with margin → add fallback → pin → re-eval on change (Chapter 14).

### Hosting

```
Demo / few users ─► one VM + Compose (+ backups)
Small production, one team ─► VM or PaaS (Fly/Render/Railway) + managed DB
Spiky traffic, tiny ops team ─► serverless containers + managed DB/Redis
Many services/teams/compliance ─► Kubernetes (managed) + GitOps
Customer mandates a platform ─► containers + 12-factor config make you portable
```

## 34.4 The starter skeleton

Create these on day one (names from this repo; adapt to your product):

```
product/
├── services/
│   ├── api/                      FastAPI app (create_app factory), tests/, migrations/, Dockerfile
│   └── tools/                    private tool server (only if tools need a privilege boundary)
├── apps/web/                     UI (or a Streamlit/Gradio prototype first)
├── prompts/<feature>/            versioned prompt files (name.vN.md)
├── evals/ (or apps/evals)        dataset + scorers + runner (exit code 1 on gate failure)
├── infra/                        reverse-proxy config, observability config
├── scripts/                      key generation, env initialisation, backup, restore (never print secrets)
├── docs/                         canvas, ADRs, runbooks, deploy guide, threat model, this book's checklists
├── docker-compose.yml            dev stack
├── docker-compose.prod.yml       hosted layout (only the proxy publishes ports)
├── .env.example                  names + safe defaults (no secrets), enforced by a test
├── .gitignore / .dockerignore    .env*, keys, node_modules, caches
└── .github/workflows/ci.yml      tests, evals, build, scan
```

### The first 30 things to build (in order)

1. Repo, `.gitignore`, `.dockerignore`, `.env.example`, **hygiene test** (no secrets).
2. `Settings` class (pydantic-settings), env-driven, secure defaults.
3. `create_app()` factory with `/health`, JSON logging, request/trace ids, security headers.
4. DB pool + **migration runner** + `001_init.sql` (constraints, indexes).
5. **Auth**: register/login, Argon2id, short access token + rotating refresh token, lockout, uniform errors, audit entries.
6. **Ownership-checked** resource endpoints; negative tests.
7. **LLM seam** (`get_llm`, config-driven provider/model) + `InstrumentedLLM`.
8. **Structured output** helper with validation and bounded retries; Pydantic schemas with validators.
9. **Fake model** (`ScriptedLLM`) and `BACKEND_MODE=demo` (refused in prod).
10. **Workflow/agent graph** with state, interrupts if needed, checkpoints in Postgres; hard loop caps.
11. **Tool adapter seam** + recorded fixtures + fake provider.
12. **Verifier** with evidence, three-valued logic, decoy tests.
13. **Enforcement in code** of every business promise (budget, limits).
14. **Streaming endpoint** (SSE) with correct headers and always-terminating events.
15. **Rate limits** and **spend caps**; per-user identity propagation to tools.
16. **Private tool server** (if needed): signed tokens, host/origin checks, replay protection, fail-closed startup.
17. **Prometheus metrics** (no user data), dashboards, alerts.
18. **Eval dataset + scorers + runner** with gates; test the gates can fail.
19. **UI** with streaming progress, uncertainty labels, error states, accessibility.
20. **Dockerfiles**: multi-stage, non-root, exec-form CMD, healthcheck, no secrets.
21. **Compose (dev)** and **Compose (prod)**: private network, one public door, health-gated startup, hardened flags.
22. **Reverse proxy** with path allow-list, automatic HTTPS, streaming-friendly flushing.
23. **Scripts** that generate keys/secrets/env files without printing them.
24. **CI**: tests with real Postgres, evals, build, scan.
25. **Backups** and a tested restore.
26. **Audit log** (append-only, hash-chained) + verification + anchoring plan.
27. **Runbooks** and the deployment guide with honest limits.
28. **Threat model** and residual-risk register.
29. **Cost model** and monitoring of spend; kill switch.
30. **README** with architecture diagram, how to run, security summary, known limits, and a link to the canvas.

## 34.5 Checklists

### Production-readiness checklist

**Product and quality**
- [ ] Success metric defined and measured; eval dataset in git; gates in CI.
- [ ] Verification/guardrails for every promise; honest uncertainty shown to users.
- [ ] Failure modes have friendly messages; no stuck states.

**Security and privacy**
- [ ] Authentication; object-level authorisation tests; admin paths protected.
- [ ] Secrets in env/secret manager; none in git/images/logs/front end; rotation plan.
- [ ] Input validation; SSRF/injection defences; prompt-injection design reviewed (no lethal trifecta).
- [ ] Rate limits and spend caps; abuse monitoring.
- [ ] Data inventory; retention and deletion implemented (including checkpoints, logs, backups).
- [ ] Third-party model/data processors reviewed (retention, training, region, DPA).
- [ ] Audit log with anchoring; admin actions audited.

**Reliability**
- [ ] Timeouts, bounded retries, circuit breakers where needed; loops capped.
- [ ] Graceful degradation and fallback model/provider.
- [ ] Health checks; restart policies; graceful shutdown covering the longest request.
- [ ] No in-process state that breaks with more than one instance (or documented single-instance limit).
- [ ] Backups automated; restore tested; RPO/RTO stated.

**Observability and operations**
- [ ] Structured logs with ids, no secrets/content; metrics; traces; dashboards.
- [ ] Alerts on symptoms with runbooks; uptime and certificate checks.
- [ ] Cost and token telemetry; budget alerts.
- [ ] On-call/escalation path; incident template.

**Delivery**
- [ ] CI green; images tagged by SHA; vulnerability scans.
- [ ] Reproducible deploy from a clean machine; rollback rehearsed.
- [ ] Migrations backward compatible; run as a release step.
- [ ] Config per environment; only the proxy publishes ports.
- [ ] Documentation: README, architecture, deploy guide, runbooks, decisions, limits.

### AI launch checklist

- [ ] Evals on real data meet the bar, with confidence intervals, not just a pass/fail on a few cases.
- [ ] Held-out set kept; no tuning on it.
- [ ] Live-model evals run; demo-mode limits understood.
- [ ] Fallback model configured; model/prompt versions pinned; change process defined.
- [ ] Shadow or pilot stage planned; human review for risky outputs.
- [ ] Red-team suite run; attack success rate tracked.
- [ ] Feedback capture linked to traces.
- [ ] Spend per conversation known and capped.

### Privacy checklist

- [ ] What personal data do we collect, why, where is it stored (including model providers, logs, caches, checkpoints), for how long?
- [ ] Consent/notice text; lawful basis; children policy.
- [ ] Deletion and export procedures tested end to end.
- [ ] Redaction before sending to third parties where possible.
- [ ] Access to production data restricted and audited.

### Day-2 operations checklist (weekly/monthly)

- [ ] Review dashboards, error budget, cost.
- [ ] Review a sample of conversations (with permission) and add eval cases.
- [ ] Dependency and base-image updates with evals.
- [ ] Restore drill; key/secret rotation per schedule.
- [ ] Check certificate expiry and quotas.
- [ ] Postmortem actions closed.

## 34.6 Templates

### Architecture decision record (ADR)

```
# ADR-007: Keep the tool server private and authenticate with single-use signed tokens
Status: accepted      Date: ...      Deciders: ...
Context: The tool server spends paid credits and fetches URLs; the model must not reach it directly...
Options: (A) in-process functions  (B) public service with API key  (C) private service with signed single-use tokens
Decision: C
Consequences: + blast radius bounded; + verifier cannot mint tokens; - extra service to run; - per-process replay memory limits scale-out (needs Redis)
Revisit when: more than one tool-server replica is needed
```

### Eval case

```yaml
id: missing-budget
input: "I need clothes for college"
simulated_user_answers: { budget: "around 3000 rupees" }
expect: { asks: [budget], budget_cap: 3000, outfits: 4 }
notes: "Regression for: agent must ask only for what is missing."
source: prod-trace-2026-10-01 (anonymised)
```

### Runbook entry

```
ALERT: HighChatErrorRatio
Meaning: >5% of chat turns failing for 10 minutes.
Check: 1) dashboard "Health"; 2) docker compose logs --tail=200 api | jq 'select(.level=="ERROR")'; 3) mcp_limit_hits_total, mcp_auth_refusals_total; 4) provider status pages
Likely causes: model provider outage/rate limit; search credits exhausted; DB connections; recent deploy.
Mitigate: roll back to previous SHA; raise credit cap (documented); switch STYLIST_MODEL to fallback; enable degraded message.
Escalate to: ...      Postmortem needed if impact > 30 minutes.
```

### Prompt-change pull request description

```
What changed: plan_outfits v2 -> v3 (adds reasoning field)
Why: garment variety scorer averaged 0.62
Eval before/after (offline + live subset): variety 0.62 -> 0.81; budget gate unchanged (1.0); calls +1; p95 latency +2.1 s; cost +$0.002/conversation
Risks: longer outputs; schema change (new optional field)
Rollback: set load_prompt("plan_outfits", 2)
```

### Model selection scorecard

| Criterion | Weight | Model A | Model B | Model C |
|---|---|---|---|---|
| Quality on our eval (primary metric) | 40% | | | |
| p95 latency | 15% | | | |
| Cost per task | 20% | | | |
| Structured output / tool reliability | 10% | | | |
| Privacy/retention/region fit | 10% | | | |
| Rate limits / availability | 5% | | | |

## 34.7 Applying the blueprint to other products

| Product | AI role | Tools/data | What must be **verified in code** | Biggest risks | Autonomy start |
|---|---|---|---|---|---|
| **Support copilot** | understand, draft, route | order/CRM APIs (read-only first), policy RAG | facts vs system of record, refund limits, templates for commitments | wrong promises, PII, injection via ticket text | draft + human approve |
| **Document Q&A** | rewrite query, answer from context | hybrid retrieval, ACLs | citations support claims; ACL filter at retrieval | cross-user leakage, stale docs, hallucination | answer with citations |
| **Data analyst (text-to-SQL)** | write queries, explain results | read-only DB role, schema docs | query allow-list, row/time limits, parameterisation, sanity checks on results | destructive/expensive queries, wrong joins | suggest query, user runs |
| **Extraction pipeline** | extract fields from documents | OCR/vision, ERP | arithmetic and format validators, duplicates | silent errors at scale | auto above confidence, humans below |
| **Content generation** | draft text/images | brand guidelines RAG | banned claims, legal text, brand checks, moderation | misinformation, IP, brand risk | draft + review |
| **Coding assistant** | write/modify code | repo, tests, sandbox | tests pass, lints, no secrets, diff review | insecure code, supply chain, prompt injection in repo | propose patch |
| **Voice bot** | speech-to-intent, dialogue | telephony, CRM | identity verification, action confirmation | latency, misrecognition, fraud | narrow flows + handoff |
| **Recommendation/stylist (this app)** | plan, explain | search API, catalogue | product attributes vs request, budget, men's only | wrong products, cost, data sparsity | suggest + links |
| **Research agent** | plan, read, synthesise | search/browse, sandbox | citations verified, budgets | injection from pages, cost loops | long job + report with sources |

**What stays constant:** the model proposes; code verifies and enforces; evals measure; observability explains; security limits the blast radius; honesty about uncertainty builds trust.

## 34.8 Why AI projects fail (and the antidotes)

| Failure pattern | Antidote |
|---|---|
| Impressive demo, no path to production | walking skeleton with production concerns early; honest gap list |
| No success metric | canvas item 3; stakeholders sign off |
| "It works" with no evals | eval dataset from day one; gates |
| Over-trusting the model | verification and enforcement in code |
| Overbuilding (agents, microservices, Kubernetes) for a simple need | simplest thing that works; justify each component |
| Ignoring data quality and access | validate data in week one |
| Security and privacy bolted on at the end | threat model in design; hygiene tests in CI |
| Cost surprises | cost model, caps, telemetry |
| Fragile to model/vendor change | seams, pinning, fallbacks, evals |
| No owner after launch | runbooks, on-call, SLOs |
| Users do not adopt | involve users early; UX for uncertainty; training |
| Scope creep | non-goals list; ADRs |

## 34.9 A boring, effective default stack

* **Backend**: Python 3.12, FastAPI, Pydantic, psycopg, LangGraph (only if you need state/HITL), `uv`.
* **Front end**: Next.js/React (or Streamlit/Gradio for first demos).
* **Data**: Postgres (+ pgvector if you need vectors), Redis when you scale out.
* **Models**: one gateway/seam (`get_llm`), structured outputs, a fallback.
* **Tools**: MCP server or plain adapters; private network; signed requests.
* **Observability**: JSON logs, Prometheus, Grafana, OpenTelemetry traces; an LLM-trace tool if useful.
* **Evals**: pytest/vitest + your own harness (or Mastra/promptfoo/Langfuse).
* **Delivery**: Docker, Compose on a VM first, GitHub Actions, Caddy, backups.
* **Security**: Argon2id, short JWTs + rotating refresh, secret manager, SAST/SCA in CI.

Deviate only for a stated reason.

## Common mistakes

* Starting with technology instead of the problem and metric.
* Building the clever part first and the verification last.
* Having no seams, so provider changes ripple everywhere.
* Skipping the canvas and ADRs, then forgetting why.
* Treating checklists as paperwork instead of design inputs.

## Summary

* A repeatable lifecycle: frame → validate → design → walking skeleton → correct → safe → persistent and visible → deploy → operate → improve.
* A one-page canvas and decision trees force the important choices early (AI or not, workflow or agent, RAG or fine-tune, async or not, where to host).
* Start every project from the same skeleton and the same first 30 steps; use the checklists and templates.
* The same principles apply to every AI product type; only the verifiers, tools and risks change.

## Key terms

*canvas, walking skeleton, seam, ADR, gate, shadow mode, autonomy ladder, residual-risk register, runbook, model scorecard.*

## Interview questions

1. How do you start an AI project? What do you do in the first week?
2. How do you decide between a workflow and an agent? RAG and fine-tuning?
3. What is a walking skeleton and why start with fakes?
4. What goes in a production-readiness review for an AI feature?
5. Apply the blueprint to a support copilot: what is verified in code?

## Exercises

1. Pick an idea (for example "an AI assistant for a clinic's appointment desk"); fill the canvas and write three ADRs.
2. Generate the skeleton repo for it with the first 30 steps as GitHub issues; build steps 1-12 offline with fakes.
3. Run the production-readiness checklist against *this* repository and write the gap list (compare with Appendix D).
4. Choose two product types from 34.7; write what you would verify in code, what you would evaluate, and your autonomy starting point.
