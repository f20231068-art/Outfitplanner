# Chapter 37. The Four Questions Every AI Engineer Must Be Able to Answer

> *"Why did the retrieval fail?"  ·  "How would you evaluate this system?"  ·  "What happens when traffic increases 100x?"  ·  "Why is the model hallucinating?"*

These four questions come up in every interview, every customer review and every production incident. This chapter gives each one a **complete, reusable answer**: a mental model, a step-by-step diagnostic or design procedure, the concrete evidence to look at in *this* project, a worked example, and a 90-second spoken answer. Each section stands alone; each links to the chapters with the full theory.

> **How to use it.** When you meet one of these questions, do not improvise. Run the procedure: **clarify → locate → measure → explain → fix → prevent**. The best answers sound the same every time because the method is the same.

**Contents**
1. [Why did the retrieval fail?](#371-why-did-the-retrieval-fail)
2. [How would you evaluate this system?](#372-how-would-you-evaluate-this-system)
3. [What happens when traffic increases 100x?](#373-what-happens-when-traffic-increases-100x)
4. [Why is the model hallucinating?](#374-why-is-the-model-hallucinating)
5. [One method behind all four](#375-one-method-behind-all-four)

---

## 37.1 Why did the retrieval fail?

### Step 0: say what "retrieval" means here (always clarify first)

The word covers two things; answer for the right one.

| Meaning | In this project | In a typical RAG system |
|---|---|---|
| **Retrieval of candidates from a source** | `search_products` → SerpAPI Google Shopping → parsed products | embed query → vector/keyword search → top-k chunks |
| **Selection among candidates** | the **verifier** accepts/rejects each product; best verified is chosen | reranker and context assembly |
| **What reaches the model or the user** | outfits shown; planner receives only `notes` | the prompt context |

The principle that organises every diagnosis (Chapter 10): **a failed answer has a retrieval half and a generation half; find which half broke before changing anything.** If the right information never reached the next stage, no amount of prompt tuning can fix it.

### The failure-location ladder (check in this order; stop at the first break)

```
1. Was the QUERY good?               (what exactly did we ask the source?)
2. Did the SOURCE return anything?   (empty, error, throttled, wrong region)
3. Did our FILTERS discard it?       (allow-lists, price caps, dedupe)
4. Did PARSING lose or distort it?   (schema/provider format drift, missing fields)
5. Did VERIFICATION/RANKING reject it?  (the right item was there but scored out)
6. Did CACHE/STATE serve STALE data? (old results, expired ids)
7. Did ACCESS/LIMITS block it?       (auth, rate limit, credit cap, ACL, network)
8. Did the right item REACH the user/model?  (truncation, k too small, ordering)
```

### Applied to AI Stylist: layer by layer, with the evidence to inspect

| # | Layer | How it fails here | Evidence you can look at |
|---|---|---|---|
| 1 | **Query** | the planner asked for something unsearchable ("peach baggy cargo pants"); the item/colour/fit words over-constrain; `build_query` always prepends `men`, de-duplicates words | the tool result's **`query_used`**; the planner's `outfit_specs` in the checkpoint; the `notes` fed back ("no verified match for 'peach chinos'") |
| 2 | **Source** | SerpAPI returned few/no `shopping_results`; provider error (HTTP 200 with `error`); 429/5xx after retries; wrong `gl`/`hl` | `UpstreamError` messages; the shopper message "I couldn't search the stores just now"; `mcp_tool_calls_total{outcome="error"}`; logs "search provider ... after N tries" |
| 3 | **Filters** | results from retailers not on the allow-list are dropped (`RETAILER_NOT_ALLOWED`); items above the price cap dropped (`PRICE_OVER_CAP`); results without a price skipped (`NO_PRICE`) | the tool result's **`warnings`** list with counts; compare `limit` vs returned count |
| 4 | **Parsing** | SerpAPI changed a field name; `extracted_price` missing; link is a Google page (`url_kind`) | recorded fixtures vs a fresh live response; parser tests (`test_search_products.py` uses real saved responses) |
| 5 | **Verification** | the right garment is rejected: colour word inside a brand name ("Red Tape"), synonym not in `_CANON`, neckline conflict, women's/kids' word, price over per-item cap, title lacks an item word | **`rejected`** list in the graph state (each entry has `reasons` like `color: asked 'beige', found 'black' (mismatch)`); `AttributeCheck.evidence`; the verifier tests |
| 6 | **Cache/state** | 6-hour search cache returns old prices; `product_id` expired ("Unknown or expired product_id"); with several MCP instances the buy-link lookup lands on an instance without the ref | `from_cache: true`; `mcp_cache_total{result="hit"}`; the expired-id `ToolError` |
| 7 | **Access/limits** | per-user rate limit, **daily credit caps** (10/25 in prod), invalid token (401), foreign Host (421), network/DNS | `mcp_limit_hits_total{limit}`, `mcp_auth_refusals_total{reason}`, `mcp_search_credits_spent_total`, the user-visible limit message |
| 8 | **Reach** | fewer than 4 outfits because replanning hit `MAX_RETRIES`; budget cap made every combination too expensive ("verified items exceed the total budget together") | `UnfilledSpec` reasons in `notes`; `stylist_outfits_delivered_total`; the closing message "I couldn't find all 4 within your budget" |

### A worked example

> *A user asked for "college wear, around ₹3000" and got only two outfits. Why did retrieval fail?*

1. **Locate the turn.** Take the conversation id → audit entries (`message_sent`, `outfits_delivered` with `count: 2`) → the `trace_id`. (Chapter 13's correlation chain.)
2. **Read the stage timings** from the trace/`status` events: `find_products` took 21 s and the graph went through `plan_outfits` twice (a replan) → the first pass came back short.
3. **Read the notes/rejections** in the saved graph state: `Spec 3 (chinos): no verified match for 'peach chinos'`, `Spec 4: verified items exceed the total budget together`; `rejected` shows 14 candidates for "olive green cargo pants" rejected with `price: asked <= 1100, found 1399 (mismatch)`.
4. **Interpret.** Not an outage (no search errors), not the cache. Two causes: (a) the planner proposed **rare colour/garment combinations** (low recall at the source); (b) the **per-item price caps** after `clamp_to_budget` were too low for the available stock, so correct garments failed the price check.
5. **Fix at the right layer.** Prompt (`plan_outfits.v2` already asks for 70-95% budget use; tune caps by garment type), planner notes (include the *reason* "all candidates were above the cap"), query broadening (drop fit/fabric on retry), verifier (accept `unknown` more where safe).
6. **Prevent.** Add an eval case with that budget and the expectation "four outfits"; track `no_outfits` and "fewer than 4" rates in a dashboard.

**An honest gap to say out loud:** the `rejected` list and `notes` live in the checkpoint state but are **not exposed by an API or dashboard**; today you read them from the database or in tests. A small debug endpoint (admin-only) and counters such as `stylist_search_candidates_total{result="rejected",reason="color"}` would make this question answerable in minutes. (Chapters 11 and 13.)

### The same question for a RAG system

Use the half-split first:

| Observation | Meaning | Where to look |
|---|---|---|
| The correct passage is **not in the top-k** | retrieval failure | everything below |
| It **is** in the top-k but the answer is wrong | generation failure (see 37.4) | prompt, context order, model |
| It is retrieved at rank 40 but k = 5 | recall/ranking failure | reranker, hybrid search, bigger k then rerank |

Causes of true retrieval failure, with the test that exposes each:

1. **Document never ingested / parse failure** (scanned PDF, table, wrong encoding): search the corpus for a distinctive sentence from the source; inspect parsed text.
2. **Chunking split the answer** across boundaries or buried it in a huge chunk: look at the chunk containing the sentence; try overlap/structure-aware splitting; test several sizes on your question set.
3. **Embedding mismatch**: different model for queries and documents, missing query/document prefixes, wrong language (Hinglish), domain jargon: embed the question and the known-good chunk and compute cosine; compare with another model.
4. **Dense-only retrieval missing exact tokens** (SKUs, error codes, names): try BM25; adopt hybrid with RRF.
5. **Query was conversational** ("what about in blue?"): inspect the query actually sent; add rewriting with history.
6. **Metadata/ACL filter too strict or wrong** (tenant, version, date): rerun the query without the filter *in a safe test environment* to see if it appears; check the user's groups.
7. **Stale or deleted/duplicated index**: compare source version timestamps; look for old versions outranking new.
8. **k and thresholds**: relevant item below threshold; no reranker; MMR removing the right near-duplicate.
9. **ANN approximation**: recall@k of the index vs exact search (set higher `ef_search`/`nprobe`).
10. **Operational**: index build failed, embedding API errors silently skipped documents, quota.

**Measure instead of guessing:** build 50-200 questions with the expected source passages and compute **hit rate/recall@k, MRR, nDCG** per configuration (Chapter 10). A change that improves recall@5 by 8 points but hurts faithfulness is visible only if you track both.

### The 90-second spoken answer

> "First I'd clarify what retrieval means in this system and which half failed, retrieval or generation, because the fixes are completely different. For retrieval I walk a ladder: was the query good, did the source return anything, did our filters discard it, did parsing distort it, did verification or ranking reject the right item, was the cache stale, did limits or access block it, and did it reach the next stage. In AI Stylist I'd read the tool result's `query_used` and `warnings`, the graph's `rejected` reasons and planner notes, and the metrics for cache hits, credit caps and search errors, all tied together by the trace id. In a RAG system I'd check whether the right chunk exists, whether it's in the top-k, then chunking, embeddings, hybrid search, filters and reranking, measuring recall@k on a labelled question set. Then I fix at the layer that broke, add the case to the eval set so it can't regress, and add a metric so I'd see it next time."

---

## 37.2 How would you evaluate this system?

### The principle

> **Evaluation is a map from each promise the system makes to a measurement that can fail.** If a promise has no measurement, it is a hope.

Chapter 12 is the full treatment; this is the compact, complete answer for *this* system and for AI systems in general.

### Step 1: write down the promises

For AI Stylist:

| Promise | Kind |
|---|---|
| Four outfits, each one top + one bottom | functional |
| Total within the shopper's budget | hard guarantee |
| Every product matches the request (price, garment, colour, men's) | hard guarantee |
| No duplicates; totals are arithmetically right | hard guarantee |
| Asks only for what is missing | behavioural |
| Outfits are varied and look good together | quality (subjective) |
| Responds in reasonable time at reasonable cost | performance |
| Never exposes another user's data; can't be abused for cost | security |
| Honest about uncertainty ("colour not confirmed") | trust |
| Survives failures (search down, model busy) with an honest message | reliability |

### Step 2: evaluate at every level (the pyramid)

| Level | What it tests | In this project | Missing |
|---|---|---|---|
| **Component** | verifier, parsers, limiters, token checks, SSRF | ~224 Python tests (e.g. `test_verify.py`, `test_check_link.py`, `test_auth.py`) | mutation testing; property tests |
| **Integration** | API + real Postgres + fakes | `test_http.py` (31), `test_database.py`, `test_agent.py` | live-provider contract checks |
| **End to end, black box** | a simulated shopper driving the real API | Mastra harness: 13 cases, 12 scorers, 8 **gates** + 4 soft signals | non-English, injection, follow-ups |
| **Real-model quality** | does the *actual* model plan good outfits and extract correctly? | **not done** (free-tier quota) | live eval run, taste judge |
| **Human review** | taste, tone, edge cases | not built | weekly sample review |
| **Online** | real users, real cost | metrics exist (turn outcomes, confidence mix); no feedback buttons | thumbs, Buy-click conversion, alerts |
| **Security / red team** | injection, abuse, cross-user access | many security tests; no model-level attack suite | automated injection suite |
| **Load** | concurrency, limits | none | Locust/k6 in demo mode |

### Step 3: build the dataset

Real requests (anonymised) are best; add expert-written edge cases; synthetic ones reviewed by a human; **every production failure becomes a case**. Organise by category (complete requests, missing budget, missing occasion, vague, tiny/huge budgets, non-English, injection, follow-ups). Expectations are **properties**, not exact text (budget cap, asked fields, outfit count). Keep a **held-out** set you never tune on; version it in git. (This repo: `apps/mastra/src/evals/cases.ts`, 13 cases.)

### Step 4: choose scorers (deterministic first)

* **Deterministic, free, run on every case**: outfit count, within budget, all items verified, men's only, no duplicates, price integrity, asks-only-what's-missing, no errors; soft: garment variety, confirmed-colour share, latency, call efficiency.
* **Model-graded** for subjective quality (colour coherence, occasion fit): rubric, reasoning-then-verdict, pairwise comparison with randomised order, a stronger different judge, **calibrated against 50-100 human labels** (report agreement).
* **Human**: a weekly random sample plus every thumbs-down and low-confidence outfit.
* **Implicit**: Buy clicks, link `live` rate, completion rate, retry/regeneration.

### Step 5: separate gates from signals

**Gates** = promises that must hold for every case (exit code 1, fail CI). **Soft signals** = trends you discuss. If everything is a gate the suite is ignored; if nothing is, it never stops a bad release.

### Step 6: be statistically honest

13 passing cases ≈ a **95% lower bound near 77%** on the true pass rate (Wilson interval); zero failures in n trials bounds the failure rate near 3/n (here ~23%). Run non-deterministic live evals **several times** and report mean and spread; use paired comparisons for A/B; never tune on the test set. Say what the eval does **not** cover: **demo mode proves plumbing and guarantees, not real-model quality or taste.**

### Step 7: wire it into delivery and production

* Offline deterministic evals + unit/integration tests **on every PR**; live eval **nightly/pre-release** with a spend cap; smoke subset on release candidates.
* **Canary** a new prompt/model on a small traffic share with outcome metrics (delivery rate, no-outfit rate, Buy-click rate, errors, cost per conversation) and automatic rollback criteria.
* **Production monitoring**: SLIs (turn success, p95 turn time, outfit delivery rate), dashboards, alerts, sampled trace review, drift detection after provider changes.
* **Feedback loop**: thumbs/"wrong item" tied to trace ids → new eval cases.

### Step 8: red-team and test the tests

Attack suite (direct/indirect injection, PII extraction, cross-user access, cost abuse); track **attack success rate**. Include known-bad cases that **must** fail (the repo's `report.test.ts` proves "the pass/fail gate can really fail").

### Evaluation of the other dimensions

* **Retrieval**: recall@k, MRR, nDCG on labelled queries; verifier **precision/recall** on hand-labelled products (precision protects users; recall decides how often four outfits can be filled).
* **Latency/cost**: p50/p95 per stage, calls per conversation, tokens, credits; budget per conversation.
* **Reliability**: chaos tests (search down, model rate-limited, DB restart), restore drills.
* **Security**: negative tests, SSRF suite, secrets hygiene tests, dependency scans.
* **Usability**: task success in user tests, accessibility checks.

### A concrete scorecard you can present

| Dimension | Metric | Target | Current evidence | Gap |
|---|---|---|---|---|
| Guarantees | gate pass rate | 100% of cases | 13/13 in demo mode | live runs, more cases |
| Product match | verifier precision | ≥ 99% | tests + decoys, not measured on labels | label 200 pairs |
| Coverage of 4 outfits | share of conversations with 4 outfits | ≥ 80% | unknown on live data | live eval |
| Quality | judge score vs human agreement (κ) | κ ≥ 0.6 | none | build judge |
| Latency | p95 turn time | < 60 s | ~30 s typical | production data |
| Cost | credits + tokens per conversation | < budget | estimated | telemetry |
| Safety | attack success rate | ~0% | partial | injection suite |
| Reliability | turn success rate (SLO) | 99% | n/a | alerts |

### The 90-second spoken answer

> "I'd start from the promises the system makes (four outfits, within budget, every product verified, men's only, honest uncertainty, bounded cost, safe) and map each to a measurement. Deterministic checks go first because they're free and repeatable: that's the 12 scorers, with 8 hard gates that fail CI and 4 soft signals. Beneath that are unit and integration tests with a real Postgres; above it a dataset of realistic and adversarial cases with property-based expectations and a held-out set. For subjective quality I'd add an LLM judge calibrated against human labels, plus a weekly human review. I'd be honest about statistics: 13 passing cases only bounds the pass rate near 77%, and demo mode proves plumbing, not model quality, so I'd run live evals within a budget. Then I'd put it in delivery: PR checks, nightly live runs, canaries with rollback criteria, production SLIs, feedback turning failures into new cases, and a red-team suite for injection and abuse."

---

## 37.3 What happens when traffic increases 100x?

### The method

1. **Establish the baseline with numbers** (never answer "it depends" without a baseline).
2. **Convert to rates and concurrency** (Little's Law).
3. **Walk the request path and rank the first things to break**, by resource.
4. **Say what you do at 2x, 10x and 100x**: different answers at each scale.
5. **Name what you would measure** to confirm.

### Baseline (Chapter 30's estimate)

50,000 monthly users → ~6,700 conversations/day; one heavy planning turn each, ~30 s, 8 searches (60% cache misses), ~4 model calls. Peak ≈ 0.28 heavy turns/s → **~9 concurrent turns**, ~32,000 search credits/day, ~27,000 model calls/day, ~335,000 database rows/day (~3 GB/month of checkpoints).

### At 100x (all numbers assume the same behaviour per conversation)

| Quantity | Baseline | 100x | Consequence |
|---|---|---|---|
| Heavy turns at peak | 0.28/s | **28/s** | |
| Concurrent turns (L = λW, W = 30 s) | ~9 | **~840** | one process has ~40 threads → **~21 processes** (or an async rewrite) |
| Open SSE connections | ~9 | ~840 | fine for Caddy/Next, but file descriptors, LB idle timeouts, and per-connection memory need checking |
| Model calls | ~0.3/s avg, ~1.5/s peak | ~31/s avg, ~150/s peak | **provider rate limits (RPM/TPM)** and spend; the free tier is irrelevant |
| Search credits/day | ~32,000 | **~3.2 million** | **unaffordable and above any plan**: the first hard wall |
| DB rows/day | ~335,000 (≈4/s) | ~33.5 million (≈390/s avg, >1,500/s peak) | Postgres can take it, but it needs tuning, retention, and probably partitioning |
| Checkpoint storage | ~3 GB/month | **~300 GB/month** | retention policy and likely a separate database |
| Audit appends | ~6 per conversation | ~46/s avg, ~230/s peak | **global advisory lock serialises every append**: a throughput ceiling near a few hundred/s |
| Connections to Postgres | 15 per API process | 21 processes × 15 = **315** | exceeds default `max_connections` (100) → PgBouncer, pool sizing |
| Redis-less in-memory state | works for one instance | **breaks** with 21 instances | limits ×21, replay protection ×21, turn lock ineffective, caches per instance |
| Caddy / single VM | fine | **single point of failure and too small** | load balancer, multi-AZ |

### What breaks first, in order (the most important part of the answer)

1. **Cost walls before capacity walls.** The paid search quota/credits (and then model spend) are exhausted long before CPU is. Without caching, precomputation or a different data source (affiliate/catalogue feed), 100x is *financially* impossible. **Protect first:** budgets, caps, kill switch.
2. **Correctness of limits and locks with more than one instance.** Per-process rate limiters, login lockout, the one-turn lock, the replay guard, credit ledger and the tool server caches (including the `detail_refs` that buy links need) all assume **one** instance. You cannot add instances safely until they live in Redis/Postgres. (Chapter 32.)
3. **Provider rate limits and latency tails** (model and search): 429s; fan-out of 8 searches multiplies tail latency; needs queueing, fallbacks, circuit breakers.
4. **Thread-per-turn concurrency**: ~840 concurrent turns means many processes or an async design.
5. **Postgres**: connection count, the audit advisory lock, checkpoint growth, write amplification.
6. **Single VM / no redundancy**: restart = downtime; need multi-instance, managed DB, load balancer.
7. **Observability and ops**: log volume, metric cardinality (route templates keep it bounded), alerting, on-call.
8. **Abuse**: at 100x, signup bots and credit-draining become real; CAPTCHA, email verification, per-IP caps, WAF.

### What you do at each step

| Scale | Actions |
|---|---|
| **2x** | nothing architectural: paid model, backups, alerts, CI, per-turn deadline, cost telemetry |
| **10x** | Redis shared state; DB lease for the turn lock; 3-4 API instances behind a load balancer; PgBouncer; managed Postgres; retention for checkpoints; gateway for model fallbacks; raise provider limits; load-test in demo mode |
| **100x** | async agent (or many instances) + autoscaling; **replace scraped search with a catalogue/affiliate feed or heavy precomputation and caching** (the cost wall); sharded or batched audit writes; partitioned/archival checkpoint storage and audit log; model routing (small model for extraction) and prompt caching; queue-based load leveling for provider limits; multi-AZ, CDN/WAF, bot defence; SLO-driven operations; cost per conversation as a tracked product metric |

### How you would confirm (never assume)

* **Load test in demo mode** (Locust/k6) to find the first internal bottleneck without spending money: thread pool, DB connections, audit lock, latency percentiles.
* **Small live calibration** to measure real tokens/credits per conversation.
* **Dashboards** for `stylist_active_chat_turns`, stage timings, `mcp_limit_hits_total`, rate-limited counts, DB connections, queue depth.
* **Failure drills** at scale: kill an instance mid-stream; stop Redis; throttle the provider.

### The 90-second spoken answer

> "I'd start from a baseline: about 9 concurrent heavy turns and ~32k search credits a day for 50k users. At 100x that's roughly 840 concurrent turns, 3 million credits a day, 150 model calls a second at peak, and hundreds of database writes a second. The first thing that breaks is cost, not CPU: the search quota is exhausted, so I'd need caching, precomputation or a catalogue feed. Second is correctness: my rate limiters, the one-turn lock, the replay guard and the tool server's caches are in process memory, so more than one instance weakens limits and even breaks buy links until I move them to Redis and Postgres. Then provider rate limits and tail latency, thread-per-turn concurrency, Postgres connections and the audit log's global lock, and finally redundancy. At 2x I'd just harden; at 10x I'd externalise state and run a few instances behind a load balancer with managed Postgres; at 100x I'd go async or autoscale, change the data source, partition storage and add multi-AZ and bot defence. And I'd confirm each step with a demo-mode load test and a small live calibration."

---

## 37.4 Why is the model hallucinating?

### First, define the problem precisely

Not every wrong answer is a hallucination. Classify before diagnosing:

| Symptom | Likely class | Where the fix lives |
|---|---|---|
| States facts/entities/URLs that don't exist; invents product details | **hallucination (fabrication)** | grounding, verification |
| Answer contradicts the provided context | **unfaithfulness** (generation failure) | prompt/context/model |
| Right answer was never in the context | **retrieval failure** | Section 37.1 |
| Misreads an ambiguous request | **ambiguity**, not fabrication | clarifying questions, schema |
| Wrong arithmetic/counting | **capability limit** | use code/tools |
| Follows instructions hidden in data | **prompt injection** | Chapter 21 |
| Plausible but outdated | **stale knowledge** | retrieval/tools |
| Agrees with a wrong premise | **sycophancy** | critique prompting, evals |

### Why models hallucinate (the mechanism, in two sentences)

A language model produces the **most plausible continuation** of the text, not a checked fact, and it has **no built-in "I don't know" detector**; when the needed information is missing, ambiguous or buried, plausibility fills the gap, and **output formats can pressure it to produce a value** (a required field must contain *something*).

### The causes, with the diagnostic test for each

| Cause | How to recognise it | Test that confirms it |
|---|---|---|
| **No grounding**: facts requested but none supplied | answer contains specifics (prices, links, stock) not in context | check the exact prompt/context: was the information there? |
| **Information missing, but the schema demands a value** | fields filled with plausible defaults | make the field nullable/add `"unknown"`; see if fabrications become nulls |
| **Ambiguous or underspecified prompt** | different runs give different "facts" | rewrite explicitly; add "if not stated, say unknown"; measure variance |
| **Long, noisy or badly ordered context** | correct info present but ignored; middle-of-context loss | shorten, reorder, reduce k; compare |
| **Weak or small model / heavy quantisation** | more fabrication on hard cases | same prompt on a stronger model |
| **High temperature / sampling** | inconsistent details | temperature 0-0.2; run N times |
| **Retrieval failure** | context lacks the answer, model improvises | inspect retrieved chunks (37.1) |
| **Stale knowledge** | confidently wrong recent facts | add search/tools or dates |
| **Task beyond capability** (counting, exact math, long reasoning) | confident wrong computations | give a calculator/code or break into steps |
| **Prompt injection or poisoned context** | answer follows instructions found in data | inspect context for embedded instructions |
| **Sycophancy / leading questions** | agrees with false premises | neutral rephrasing; ask for counter-arguments |
| **Training-data gaps** (rare entities, local brands) | fabricated names/links | require citations from supplied sources |

### The diagnostic procedure

1. **Reproduce** with a stored trace: exact prompt, schema, parameters, model and version, tool results.
2. **Was the truth available?** Search the context for the correct fact. *Not there* → retrieval/grounding problem; *there but ignored* → generation/context problem.
3. **Check the output format**: did a required field force a guess? Does the schema allow "unknown"?
4. **Vary one thing at a time**: temperature, model, context length/order, prompt wording; run ≥ 10 times to separate random from systematic.
5. **Look for contradictions** between output and context automatically (a groundedness check).
6. **Check for injection** in any untrusted text in the context.
7. **Quantify**: what fraction of outputs fabricate, on which inputs? A single bad example is an anecdote.
8. **Fix the layer, then add the failing case to the eval set** and re-measure.

### Where hallucination could occur in this app, and why the damage is bounded

| Step | What the model produces | What a hallucination would look like | Containment |
|---|---|---|---|
| `gather_prefs` | `budget_inr`, `occasion` | a budget the user never said | "Extract ONLY what the shopper said ... Never guess"; nullable fields; validators; `missing` triggers a question; evals check "asks exactly what is missing" |
| `propose_styles` | five style names/descriptions | odd or off-topic styles | schema; low harm; shown as choices |
| `plan_outfits` | item/colour/fit/price caps | impossible or unsearchable items; caps summing above budget | `clamp_to_budget` (code); items are only **search queries**, not claims |
| search + `verify_product` | *none*: products come from the provider | n/a: **the model never names products, prices, links or stock**; the verifier checks them against provider data | structural: the product facts are never model-generated |
| `rationale` text | explanation of why items go together | claims about the items that are untrue | shown as plain text; informational; **could be verified** against item colours/garments |
| `respond` | summary | n/a (written by code from verified data, no model call) | deterministic |

**The design principle:** *remove the model from the path of factual claims.* Hallucination risk is highest where a model states facts; this system arranges that the only facts a user sees (titles, prices, retailers, links, totals) come from search data and Python arithmetic. What remains is "soft" content (style names, rationales), where an error is harmless, and where a verifier could still be added.

### Mitigations, in order of effectiveness

1. **Ground**: provide the facts (retrieval/tools) and instruct "answer only from the context; otherwise say you don't know".
2. **Remove the model from fact production** (compute, look up, or copy from data in code).
3. **Constrain the output space**: schemas, enums, nullable/`unknown` fields.
4. **Verify**: deterministic checks that claims appear in the data; reject or flag failures.
5. **Cite** sources and let users check; verify citations.
6. **Right-size the model and parameters**: stronger model for hard steps, low temperature for factual tasks, reasoning effort where multi-step.
7. **Reduce context noise**: fewer, better chunks; good ordering.
8. **Allow and reward abstention**: evals that score "I don't know" correctly.
9. **Human review** for high-stakes outputs.
10. **Monitor**: groundedness scorers on samples, user feedback, alert on spikes.

### Measuring a hallucination rate

* **Faithfulness/groundedness**: for each claim in an answer, is it supported by the supplied context? Use a calibrated LLM judge plus spot human checks, or deterministic matching (numbers/names/links must appear in the context).
* **Abstention accuracy**: when the answer is not in the data, does it say so?
* **Citation accuracy**: do cited sources support the claim?
* Track **per-prompt-version and per-model** so regressions are visible; report intervals, not single numbers (Chapter 5).

### A worked example

> *The `rationale` says "the olive henley pairs with the Levi's jeans", but the outfit contains an Amazon polo and chinos. Why?*

1. Reproduce from the trace: the planner produced `rationale` **at planning time**, before any product existed; the final products are chosen later by search and verification (different brands/garments possible).
2. Truth available? No: the model could not know which products would be found. So this is **ungrounded generation**, not a bug in the model.
3. Fix: either (a) generate the rationale **after** selection using the verified item titles as context (grounded), or (b) restrict it to what the plan controls (colours/garment types) and have code insert brand names, or (c) add a deterministic check that every product/brand named in a rationale appears in the outfit.
4. Add an eval scorer and a case; re-measure.

### The 90-second spoken answer

> "First I'd classify the failure: is it fabrication, unfaithfulness to provided context, a retrieval failure, ambiguity, a capability limit like arithmetic, or an injection? Models produce plausible text, not checked facts, and structured outputs can force a value when none is known. So I reproduce with the stored trace and ask: was the truth in the context? If not, it's grounding or retrieval; if yes, it's context order, noise, model strength or temperature. I vary one factor at a time over several runs, check whether the schema allowed 'unknown', and look for injected instructions. Fixes in order: ground the model, take it out of the path of factual claims, constrain outputs, verify with code, cite, right-size the model, and measure with groundedness and abstention scorers. In this app the model never states product facts: products, prices and links come from search data and are verified by rules, and budgets are clamped in code; what's left, like the rationale text, I'd ground by generating it after selection."

---

## 37.5 One method behind all four

| Question | The reflex |
|---|---|
| Retrieval failed | **Locate**: walk the ladder from query to delivery, using the evidence each layer leaves. |
| Evaluate the system | **Map promises to measurements**: layers, dataset, scorers, gates, statistics, production. |
| 100x traffic | **Baseline → rates → bottlenecks in order → actions per scale → how to confirm.** |
| Hallucination | **Classify → was the truth available → vary one factor → fix the layer → measure.** |

Common to all: **be quantitative, name the evidence you would look at, separate causes by layer, fix at the cause, add a test or metric so it cannot silently recur**, and **say what you do not know and how you would find out**.

### The pre-flight checklist before answering any "why/how/what if" question

- [ ] Did I clarify the term (what does "retrieval/evaluate/traffic/hallucinating" mean here)?
- [ ] Do I have a baseline or a concrete example?
- [ ] Did I decompose by layer or resource?
- [ ] Did I name specific evidence (logs, metrics, traces, state, tests)?
- [ ] Did I rank causes or bottlenecks, not list them?
- [ ] Did I propose a fix **and** a prevention?
- [ ] Did I state limits and unknowns honestly?

## Common mistakes

* Answering "retrieval failed" by tweaking the prompt, or "hallucination" by lowering temperature, without locating the layer.
* Evaluating only on the happy path or only with demos; claiming quality from a tiny eval set.
* Answering "scale it" with "add servers" without naming the cost wall, the shared-state problem, or the provider limits.
* Treating all wrong answers as hallucinations.
* Not leaving any trace of the failure (no logs, no saved state), so the question cannot be answered later.

## Exercises

1. For a conversation of your own, answer 37.1 using only the evidence you can actually retrieve; list what you wished you could see and add it (a counter, a log field, an admin debug endpoint).
2. Write the scorecard in 37.2 for a different AI system (a support bot) and mark current evidence and gaps.
3. Redo the 100x table with your own baseline and identify the first three failures; then run a demo-mode load test to see whether your prediction was right.
4. Create ten test inputs that tempt the planner to hallucinate (ambiguous occasions, impossible colours); measure the fabrication rate before and after making `rationale` grounded.
5. Record yourself answering each question in 90 seconds; watch for hand-waving and missing numbers.
