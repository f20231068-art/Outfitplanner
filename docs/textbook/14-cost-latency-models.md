# Chapter 14. Cost, Latency and Model Choice

> **Learning objectives.** Build a cost model for an AI feature from tokens, calls and external APIs; apply the levers that reduce cost and latency in the right order; choose and swap models with a measured method; design spend limits and defend against "denial of wallet"; and reason about this project's actual constraints (free-tier quotas, search credits, 30-60 second turns).
>
> **Prerequisites.** Chapters 5, 6, 12, 13.

All prices and quotas in this chapter are **illustrative**. Vendors change them often. The skill you need is *calculating* with whatever the current numbers are.

---

## 14.1 Where the money and time go

An AI application's costs and delays come from a short list:

| Source | Cost driver | Latency driver |
|---|---|---|
| **LLM calls** | input tokens + output tokens (+ reasoning tokens) × price | time to first token (prompt length) + generation (output tokens × per-token time) |
| **Embedding calls** | tokens embedded | usually small |
| **Tool/API calls** | per-call or per-credit pricing (search, maps, SMS) | their latency (hundreds of ms to seconds) |
| **Infrastructure** | servers, database, bandwidth, storage, observability | network hops, cold starts |
| **Humans** | review, support, labelling | n/a |

In this app, a typical live turn is dominated by **model calls** (3-6) and **searches** (8 per planning round). Locally measured: a first live search took ~0.8 s and a cached one ~0.01 s; model calls take seconds each; a whole turn is tens of seconds.

## 14.2 The token cost model

```
cost(call) = input_tokens · p_in  +  cached_input_tokens · p_cache_read  +  output_tokens · p_out
```

* **Output tokens are priced higher than input** (often 3-5×), and are also the slow ones (generated sequentially).
* **Reasoning/thinking tokens are billed as output** even when hidden. A "thinking" model can cost several times a non-thinking one on the same prompt.
* **Everything you send counts**: system prompt, tool definitions, retrieved documents, the entire history, images.
* **Conversation history makes cost grow with each turn.** If a chat has t turns of about m tokens, turn k sends ~k·m tokens, so the total input over the conversation is ~m·t²/2, **quadratic in length**. Truncate, summarise, or cache the prefix.
* **Cached input** (prompt/prefix caching) is billed at a steep discount on providers that offer it, while *writing* to the cache may cost slightly more than normal input.
* **Batch APIs** (asynchronous, results within hours) typically cost about half.

### A worked estimate for AI Stylist (hypothetical prices, estimated tokens)

Hypothetical prices: **$1 per million input tokens, $5 per million output tokens**. Token counts below are rough estimates *you should replace with measured `usage` numbers*:

| Step | Input tokens | Output tokens | Notes |
|---|---|---|---|
| `gather_prefs` (extract) | ~350 | ~40 | system prompt + schema + short history; tool-call output is tiny |
| `propose_styles` | ~300 | ~450 | five styles with one-line descriptions and image prompts |
| `plan_outfits` | ~1,000 | ~900 | prompt + JSON context + schema; four outfit specs |
| **Typical turn total** | **~1,650** | **~1,400** | three calls |

Model cost ≈ 1,650 × $1/1M + 1,400 × $5/1M = $0.00165 + $0.007 ≈ **$0.009 per conversation**. Add a clarifying question or a replan loop and it might reach $0.02.

**Search**: 8 searches per planning round; if a search credit costs even $0.005-$0.015 on a paid plan, that is **$0.04-$0.12 per round**, **several times the model cost**. The Buy click adds one credit. Cache hits cost nothing.

**Insight:** *in this product, the search API likely dominates cost, not the language model.* That explains why the project's protection effort went into **credit caps, caching, and not calling `get_buy_link` until the user clicks**. Always compute the whole stack before optimising one part. (Verify with measured numbers; the point is the method.)

### Free-tier arithmetic (real constraint from the project)

A free model with **20 requests/minute and 50 requests/day** and a conversation using ~6 calls ⇒ ⌊50/6⌋ = **8 conversations/day**, and per-minute limit means a single conversation's calls must be paced. The hosted layout's search caps (10 per user, 25 global per day) ⇒ about 3 planning rounds per day *total*. These numbers define what the demo can promise, and why the README says "Must move to a paid model before real users."

## 14.3 Reducing cost: the levers, in order

Optimise in this order (earlier levers are free and safe; later ones trade quality or complexity):

### 1. Do not call at all

* **Use code instead of a model** for deterministic work (budget clamping, verification, formatting, routing on state). This repo's verifier and `respond` node cost zero tokens.
* **Cache results**: exact-match caches for repeated inputs (the tool server's 6-hour TTL cache of searches and buy links; hits do not reach the paid provider). **Semantic caches** for near-duplicates with high similarity thresholds (carefully).
* **Deduplicate and batch** identical requests in flight.
* **Short-circuit**: validate input *before* calling a model (empty, too long, obviously invalid).
* **Rate-limit and cap** so a loop or abusive user cannot generate unbounded calls.

### 2. Send fewer tokens

* Trim system prompts; remove stale rules (Chapter 7).
* **Return concise tool results** (select fields, truncate lists); do not paste raw pages.
* **Summarise or window the history**; keep structured state instead of replaying everything.
* Prefer **compact schemas** and short field names; avoid deeply nested JSON.
* Pass **structured summaries** between stages (the planner receives a small JSON, not the whole chat).

### 3. Use prompt (prefix) caching

Providers can reuse the processed form of an identical **prefix**, charging a small fraction for cache reads and reducing time to first token. Design for **prefix stability**: static instructions, tool definitions and examples first; per-request data last; no timestamps or random ids early in the prompt; deterministic ordering of tools and JSON keys. Verify with the cache fields in the response `usage` (cache-read tokens should be non-zero on repeated calls; if zero, something earlier in the prompt changes every time). Minimum cacheable sizes and cache lifetimes (minutes by default, longer optional) vary by provider. *This app's prompts are short, so caching saves little; it matters for apps with long system prompts, many tools, big few-shot sets, or retrieved documents reused across turns.*

### 4. Right-size the model

* Use the **smallest model that meets your quality bar on your eval set**. Extraction and classification often work on small, cheap models; ambiguous planning or reasoning may need a larger one.
* **Routing**: a cheap classifier (or rule) sends easy requests to a small model and hard ones to a large model.
* **Cascades**: try the cheap model first; escalate if a verifier or confidence check fails. (This repo already has the verifier you would need for such a cascade.)
* **Re-test when models update**: newer small models often match older large ones.

### 5. Control reasoning effort and output length

* Use the model's **effort/thinking controls**: low effort for simple stages, higher only where measurement shows improvement. Reasoning tokens are output tokens.
* **Cap `max_tokens`** to what the task needs; ask for concise output; use structured outputs instead of prose where you can.
* Lower effort/less thinking also **reduces latency**.

### 6. Batch non-urgent work

Offline jobs (embedding a corpus, nightly evals, bulk classification) can use **batch endpoints** at roughly half price.

### 7. Fine-tune or distil

For a **high-volume, narrow, stable** task, fine-tune a small model (or distil a large model's outputs into it) to get lower cost and latency with consistent format. Only after prompting, structured outputs and retrieval are exhausted, and only with an eval proving it.

### 8. Self-host open models

At very high volume, or for privacy/residency, running open-weight models on your own GPUs can be cheaper per token, but you take on **GPU procurement, serving (vLLM, TGI), scaling, monitoring and security**, and often accept a capability gap. Compute the **break-even**: monthly API spend vs GPU rental + engineering time. For most products, start with APIs.

### Measure *cost per successful task*

A cheaper model that fails more often, forcing retries and replans, can cost more **per completed outcome**. Track: cost per conversation, cost per *delivered outfit set*, tokens per stage, and the retry/replan rate. Alert on anomalies.

## 14.4 Latency: where the seconds go, and what to do

### Anatomy

`total = network + queueing + prefill (TTFT) + generation + tool calls + retries + your own code`

* **TTFT** grows with prompt length (and cold caches).
* **Generation** time ≈ output tokens ÷ tokens-per-second (20-150 tok/s depending on model and load).
* **Tool calls** (search) add 0.5-3 s each; **sequential** calls add up, **parallel** calls overlap.
* **Retries and backoff** add seconds; **rate-limit waits** add more (and show up in traces as unexplained gaps).
* **Connection setup**: a new TCP + TLS handshake costs tens to hundreds of ms. Connection reuse (keep-alive, pooled clients) avoids it. *In this repo each `McpProductSearch` call opens a new MCP client in a new event loop (`asyncio.run`), so each search pays connection setup; a shared client per worker would cut that. A good example of a deliberate simplicity-vs-performance trade.*
* **The IPv6 stall**: on some networks the first connection tries IPv6 and waits ~40 s before falling back to IPv4. The repo works around it with `force_ipv4`. *Latency bugs are often networking, not code.*

### Techniques, roughly in order of payoff

1. **Stream output and progress** (SSE): perceived latency drops dramatically. The UI shows "Understood your request", "Styles ready", "Stores searched"... as each stage completes.
2. **Parallelise independent work**: the eight searches run concurrently (`ThreadPoolExecutor(max_workers=8)`), so the stage costs about the *slowest* search, not the sum.
3. **Shrink prompts and outputs** (also saves money).
4. **Use smaller/faster models** for easy stages; use provider "fast" tiers where offered (at a premium).
5. **Cache** (results, prefixes).
6. **Precompute** what you can (style lists per occasion, embeddings).
7. **Avoid unnecessary round trips**: combine stages when quality allows (but test; fewer, bigger prompts reduce debuggability).
8. **Co-locate** services (same region/data centre); reuse connections.
9. **Set timeouts and fail fast**, with graceful messages, so slow failures do not hold resources.
10. **Optimistic UI**: show the style cards while the model drafts the plan.

### The tail at scale

When one request fans out to *n* parallel calls, the response time is the **maximum**, so rare slowness is amplified. If each call is slow 1% of the time, then with n = 8: P(at least one slow) = 1 − 0.99⁸ ≈ **7.7%**. That is why p95/p99 matter and why the stage with eight searches is the latency risk. Mitigations: per-call **timeouts**, **hedged requests** (send a backup after a delay and use whichever returns first, for idempotent calls), **partial results** (proceed with whichever searches returned; the app already tolerates failed searches via `safe_search`), and caching.

### Capacity linkage

Latency and capacity are tied by **Little's Law** (Chapter 5): shorter turns mean more turns per worker. Halving turn time doubles per-process throughput.

## 14.5 Rate limits and throughput

* Providers limit **requests per minute (RPM)** and **tokens per minute (TPM)**, and free tiers also **requests per day**. A **429** with `Retry-After` is normal.
* **Client-side**: respect `Retry-After`; use **exponential backoff with jitter**; implement a **client-side token bucket** to stay under limits proactively; queue and smooth bursts.
* **Per-user and global limits in your own API** (this repo: 10 chat messages/min/user; 30 conversations/day/user) so one user cannot exhaust a shared quota.
* **Concurrency limits**: bound parallel provider calls (a semaphore).
* **Capacity planning**: for a target of N concurrent conversations, compute TPM and RPM needs; request higher quotas or **priority/provisioned throughput** tiers when you have predictable load.
* **Multiple providers/models** as fallback when one is rate-limited or down (a gateway/router such as OpenRouter or LiteLLM, or your own adapter).

## 14.6 Choosing a model: a method

### Step 1: define the task and constraints

Write them down: input and output shape, quality bar (measured by *your* eval), latency target (TTFT and total), cost per task target, volume, context length, languages, modality, tool-calling and structured-output needs, privacy/residency/retention rules, availability needs.

### Step 2: shortlist

From providers and open models that satisfy the hard constraints. Read model cards for context window, knowledge cutoff, modalities, supported features (tool use, JSON schema, reasoning controls), rate limits, pricing and data policies.

### Step 3: measure on your data

Run each candidate on the **same eval set** (Chapter 12): quality scores, failure types, latency distribution, token usage → cost per task. Include the **hard cases**. Do not trust public benchmarks for your task. This project did this kind of testing in practice: it found that the free model rejects `json_schema`, returns nulls in JSON mode, and works through tool-calling, and it measured rate limits and conversation cost.

### Step 4: choose on the Pareto frontier

Plot quality vs cost vs latency; discard dominated options; pick the cheapest model that clears the quality bar with margin. Prefer a **simple routing** rule over a complex one unless the savings are large.

### Step 5: plan for change

* **Abstract the model** behind one function/adapter (`get_llm`) and config (`STYLIST_MODEL`).
* **Pin versions** where possible; subscribe to deprecation notices.
* **Keep evals runnable** so a migration is a few commands: run on both, compare, review disagreements, switch.
* Have a **fallback model** and a **degraded mode**.
* Beware **vendor lock-in** in prompts (format quirks), tool-calling styles, caching features and proprietary APIs; gateways reduce but do not remove it.
* Re-evaluate **every few months**; the frontier moves quickly.

### A decision table

| Need | Lean towards |
|---|---|
| Extraction, classification, routing, formatting | small/fast model, low or no reasoning, structured output |
| Planning, multi-step reasoning, ambiguous instructions | larger model, moderate effort, with verification |
| Complex coding/agentic tasks | frontier model with strong tool use, high effort, budgets |
| Long documents | long-context model + retrieval; cache the prefix |
| Strict privacy / on-prem | open-weight model self-hosted, or a provider with the right data terms |
| Very high volume, narrow task | fine-tuned small model |
| Multimodal | model with vision/audio input; test OCR-like tasks |
| Embeddings/search | dedicated embedding model (+ reranker) |

(Model names change constantly; consult current documentation and your own evals. This repo's runtime model is a free OpenRouter model chosen for development cost, which is fine for building and testing and not for real users.)

## 14.7 Prompting vs retrieval vs fine-tuning: the economic view

| Option | Up-front | Per-call | Update speed | Best for |
|---|---|---|---|---|
| Better prompt | hours | + tokens per call | instant | first resort for behaviour |
| Few-shot examples | hours | + tokens (cache them) | instant | format and judgement |
| RAG | days-weeks | + retrieval and context tokens | fast (re-index) | facts, documents, freshness |
| Fine-tuning | weeks, data and eval | − tokens (shorter prompts), cheaper model | slow (retrain) | style, format, narrow tasks at high volume |
| New/bigger model | config change | + price | instant | when quality is the bottleneck and cost allows |

## 14.8 Spend controls and "denial of wallet"

A pay-per-call API turns **abuse into cost**: anyone who can trigger calls can spend your money ("denial of wallet"), and a bug in an agent's loop does the same without any attacker. Controls (this repo implements several):

| Control | In this repo |
|---|---|
| Per-user **rate limits** | 10 chat messages/min; 10 buy links/min; tool server 60 calls/min |
| **Daily caps** | 30 conversations/day/user; search credits 40/user and 100 global (dev defaults), 10/25 in the hosted layout |
| **Hard bounds on loops** | `MAX_RETRIES`, `MODEL_ATTEMPTS`, `ATTEMPTS`, worker pool size |
| **Ownership checks** | buy-link only for products shown to *this* user (so nobody spends credits on arbitrary ids) |
| **Caching** | search and link caches; cache hits never count against credits |
| **Authentication** | no anonymous use; accounts required |
| **Input limits** | message ≤ 500 characters |
| **Auditing and metrics** | credits spent, limit hits |

Add in production: **budget alerts** from the provider and your own dashboards (spend per day, per feature), **anomaly alerts** (spend 3× normal), a **kill switch** (feature flag to disable expensive paths), **per-tenant quotas**, **CAPTCHA/proof of work** on signup if abused, and a **spend circuit breaker** that degrades to cached or cheaper behaviour when a threshold is hit. Keep **API keys** out of the browser and rotate them; a leaked key is also denial of wallet (a key that ever appears in a committed file, a log or pasted output should be treated as compromised and rotated; this project added a test that fails if a real-looking secret appears in `.env.example`).

## 14.9 Worked example: monthly forecast

Assume **10,000 conversations/month**, each with one planning round (8 searches), 40% of search queries hit the cache, 25% of conversations click Buy once (1 extra credit), and hypothetical prices: model ≈ $0.009 per conversation; search credit = $0.01.

* Model: 10,000 × $0.009 = **$90**
* Search misses: 10,000 × 8 × (1 − 0.4) = 48,000 credits → **$480**
* Buy links: 10,000 × 0.25 × 1 = 2,500 credits → **$25**
* **Total variable ≈ $595/month ≈ $0.06 per conversation.**

Sensitivity: raise cache hit to 70% ⇒ search ≈ $240 (total ≈ $355). Replan loops averaging 1.4 rounds ⇒ search +40%. If you charge for the product, the *gross margin per conversation* is a design input. Build this table in a spreadsheet with low/expected/high scenarios, and update it from real logs.

## 14.10 Practical checklist

* [ ] Log `usage` (input/output/cached/reasoning tokens) and cost per call and per conversation.
* [ ] Dashboard for cost and latency by stage.
* [ ] Caps and alerts for spend.
* [ ] Timeouts and bounded retries at every layer.
* [ ] Prompt prefix stable and cache hits verified (if applicable).
* [ ] Smallest adequate model per stage, validated by evals.
* [ ] Streaming and progress events in the UI.
* [ ] Parallelism where independent; partial-result tolerance.
* [ ] Fallback model and degraded mode.
* [ ] Re-run evals before every model change.

## Common mistakes

* Optimising prompt tokens while the search API is the real cost.
* No usage logging, so nobody knows the cost per conversation.
* Replaying the entire history forever.
* Assuming "the biggest model" is needed for every stage.
* Retrying at every layer (cost multiplication).
* Ignoring tail latency of fan-out calls.
* No spend limits on a public endpoint.
* Choosing a model from a leaderboard instead of an eval on your task.

## Summary

* Costs come from tokens (output and reasoning cost more), external API credits, and infrastructure; latency comes from prompt length, generated tokens, tool calls, retries and connections.
* Reduce cost by not calling (code, caches), sending fewer tokens, prefix caching, right-sizing and routing, controlling effort and output, batching, then fine-tuning or self-hosting.
* Reduce latency by streaming, parallelising, shrinking, caching, reusing connections, and handling the tail.
* Choose models by measuring on your data; abstract, pin, evaluate, and keep fallbacks.
* Treat spend as a security problem: limits, caps, ownership checks, alerts, kill switches.

## Key terms

*input/output/reasoning tokens, prompt caching, cache read/write, batch API, routing, cascade, TTFT, tail latency, hedged request, RPM/TPM, Retry-After, token bucket, Pareto frontier, distillation, denial of wallet, cost per successful task.*

## Interview questions

1. How would you estimate and reduce the cost of an LLM feature?
2. Why does conversation history make cost grow quadratically, and how do you fix it?
3. What is prompt caching and how do you design prompts to benefit?
4. Where would you look first if a chatbot turn takes 40 seconds?
5. Explain tail latency amplification with parallel calls.
6. How do you choose between two models? How do you handle a forced model migration?
7. What is denial of wallet and how does this app defend against it?
8. When is fine-tuning worth it? When is self-hosting?

## Exercises

1. Instrument `InstrumentedLLM` to record token usage and produce a per-conversation cost estimate with configurable prices; show it in a Grafana panel.
2. Build the monthly-forecast spreadsheet for AI Stylist with three scenarios and a sensitivity table for cache hit rate and replan rate.
3. Measure the benefit of connection reuse: modify `McpProductSearch` to share one client per worker thread and compare total `find_products` time over 20 runs.
4. Simulate tail amplification: 8 parallel calls with a 1% chance of a 10 s delay; compute the distribution of the maximum.
5. Run the eval set with two different models (or two prompt versions) and produce a quality/cost/latency table; choose one and justify.
