# Chapter 15. Vendors, Frameworks and Alternatives

> **Learning objectives.** Map the AI-application ecosystem so any unfamiliar tool can be placed ("this is another gateway", "this is another vector store"); understand every external service and framework this project uses (what it is, why it was chosen, how it is configured, its limits, its alternatives); evaluate third-party services like an FDE; and integrate them safely with adapters, contract tests and fallbacks.
>
> **Prerequisites.** Chapters 6-14.

An FDE spends much of the job choosing, integrating and debugging *other people's services* in a customer's environment. You will never memorise the whole landscape (it changes monthly), but you can learn its **layers**, so a new name is quickly slotted into a known category with known trade-offs.

---

## 15.1 The landscape by layer

| Layer | What it does | Examples (non-exhaustive) | In this project |
|---|---|---|---|
| **Model providers** | train and serve models via API | Anthropic (Claude), OpenAI (GPT), Google (Gemini), xAI (Grok), Cohere, Mistral, DeepSeek, Alibaba (Qwen), Meta (Llama, open weights) | the model behind OpenRouter (a free model in dev) |
| **Model hosts / gateways** | one API for many models, billing, routing | **OpenRouter**, Together, Fireworks, Groq, Hugging Face Inference, cloud marketplaces (Amazon Bedrock, Google Vertex AI, Microsoft Foundry/Azure OpenAI), LiteLLM (self-hosted proxy) | **OpenRouter** (and optional OpenCode Zen) |
| **Local/self-hosted inference** | run open models yourself | Ollama, llama.cpp, vLLM, TGI, LM Studio | not used |
| **Orchestration / agent frameworks** | state, flows, tools, memory | LangChain, **LangGraph**, LlamaIndex, Haystack, Semantic Kernel, Pydantic AI, DSPy, CrewAI, AutoGen, OpenAI Agents SDK, Claude Agent SDK, Google ADK, Vercel AI SDK, **Mastra** | **LangGraph** (agent), **Mastra** (evals/tracing) |
| **Tool protocols** | how tools/agents connect | **MCP**, A2A (agent-to-agent), OpenAPI/function schemas | **MCP** (FastMCP) |
| **Retrieval / vector stores** | embeddings and search | pgvector, Pinecone, Qdrant, Weaviate, Milvus, Chroma, FAISS, Elasticsearch/OpenSearch | none (search API instead) |
| **Data and search APIs** | external information | **SerpAPI**, Tavily, Brave Search API, Exa, Bing/Google APIs, Firecrawl (scraping) | **SerpAPI Google Shopping** |
| **Document parsing** | text from PDFs/pages | Unstructured, LlamaParse, Azure Document Intelligence, Textract | none |
| **Eval and LLM observability** | traces, datasets, scoring | Langfuse, LangSmith, Braintrust, Arize Phoenix, Helicone, W&B Weave, promptfoo, **Mastra evals** | **Mastra** + Prometheus/Grafana/Jaeger |
| **Guardrails and safety** | filter input/output | Llama Guard, NeMo Guardrails, Guardrails AI, provider moderation APIs | custom deterministic checks |
| **Media models** | image/audio/video | image generators, Whisper/ElevenLabs, vision models | "try it on me" blocked on provider choice |
| **App hosting** | run your code | Vercel, Railway, Fly.io, Render, Cloud Run, AWS (ECS/EKS/Lambda), Azure, a plain VM | Docker Compose on one VM (planned) |
| **Data stores** | persistence | Postgres, MySQL, Redis, DynamoDB, SQLite/libSQL, S3 | **Postgres**, libSQL (Mastra) |
| **Web/UI** | front end | Next.js, React, Vue, Svelte | **Next.js 16 / React 19** |

Learn the layers; then, for any new tool, ask: *which layer is this, what does it abstract, what does it lock me into, and what is the exit path?*

## 15.2 The services used in this project, one by one

### 15.2.1 OpenRouter (the chat-model gateway)

**What.** A hosted **gateway/marketplace** exposing hundreds of models from many providers through one **OpenAI-compatible API** (`https://openrouter.ai/api/v1`), one key, one bill. Model ids look like `provider/model` (for example `apodex/apodex-1.1-mini:free`); the suffix `:free` marks free-tier variants.

**How it is used here.** `llm.py::get_llm` builds a `ChatOpenAI` client with `base_url=openrouter_base_url` and an `X-Title: AI Stylist` header (optional attribution). `STYLIST_MODEL=openrouter/apodex/apodex-1.1-mini:free`: the first path segment selects the provider adapter; the rest is the model id.

**Why chosen.** Free-tier access for development, easy model switching, no per-vendor SDK, OpenAI-compatible so existing libraries work.

**Behaviours learned by testing (record these for any model you adopt):**
* The free model **rejects `json_schema` structured output**, and JSON mode **returned nulls**; **tool-calling works**, so `STRUCTURED_OUTPUT_METHOD=function_calling`.
* **Free-tier limits**: 20 requests/minute and 50 requests/day (for accounts with under $10 in credits). ~6 calls per conversation ⇒ ~8 conversations/day.
* Free models can be **rate-limited, slow or withdrawn** without notice, and may have different data-retention terms. Treat as development-grade.

**Gateway pros/cons.** Pros: flexibility, quick comparison, provider fallbacks. Cons: an extra hop and intermediary (latency, a second party with your prompts, availability dependence), feature support varies per underlying model, and you inherit each model's quirks. **Alternatives**: LiteLLM (self-host a proxy), direct vendor APIs, cloud-native gateways (Bedrock, Vertex, Foundry), Cloudflare AI Gateway, Portkey, Helicone.

### 15.2.2 OpenCode Zen (optional second provider)

The code also supports `opencode/<model>` through `https://opencode.ai/zen/v1`: a curated model gateway where **GPT and Grok families are served on the `/responses` endpoint** while **Qwen, DeepSeek, Kimi, GLM and MiniMax use `/chat/completions`**. `get_llm` chooses `use_responses_api` from the model name (overridable with `LLM_API_MODE`), and **Claude models there use a different endpoint style and raise `NotImplementedError`** rather than failing mysteriously. Lesson: *endpoint style differences between model families are a real integration cost; isolate them in one adapter and fail loudly on the unsupported.* (The default in `config.py` is `opencode/gpt-5.5`, overridden by `.env`'s `STYLIST_MODEL`.)

### 15.2.3 SerpAPI (Google Shopping search)

**What.** A paid API that runs Google searches (many engines, including Google Shopping) and returns **structured JSON**, so you do not scrape Google yourself (against its terms, brittle, blocked).

**How it is used here** (`providers/serpapi.py`, the only file that knows the shape):
* `search`: `GET https://serpapi.com/search.json?engine=google_shopping&q=<query>&gl=in&hl=en&api_key=...`. `gl=in` selects India, `hl=en` English.
* Results in `shopping_results`: `title`, `source` (retailer), `extracted_price` (number), `old_price`, `thumbnail`, `rating`, `reviews`, `delivery`, `product_id`, `link` (sometimes a direct store link) or `product_link` (a **Google Shopping page**), and `serpapi_immersive_product_api` (a URL for the detail call).
* `offers`: the **immersive product** API (found via that URL; **costs another credit**) lists the **stores** that sell a product, with links, prices, and stock text; this is how `get_buy_link` finds the store's own page.
* Errors sometimes arrive as HTTP 200 with an `error` field; the adapter treats that as an upstream error.
* **Credits**: each search = 1 credit, cache hits = 0. The tool server enforces per-user and global **daily caps** to protect a small quota.

**Gotchas recorded in the project.** Results link to a Google page rather than the retailer (`url_kind: google_product_page`); **colour is stated in only ~11%** of titles; the provider needs the detail URL's own query string preserved (appending `&q=...&api_key=...` rather than passing `params=` which would replace it and silently turn into a web search). *Always read the raw responses you depend on and save them as test fixtures.*

**Alternatives**: Google Programmable Search / Merchant APIs, retailer or affiliate APIs (best for production, with permission and commissions), product feeds (Admitad, Impact), Tavily/Exa/Brave (general web), Zyte/Bright Data (scraping with legal review), your own catalogue.

**Legal and ToS note an FDE should raise**: using search results commercially, caching them for hours, and linking to retailers can be restricted by the provider's terms and by retailers' terms. Check **licensing, attribution and caching rules** before launch, especially for paid products.

### 15.2.4 LangChain and LangGraph

Covered in Chapter 9. Used: `ChatOpenAI`, message classes, `with_structured_output`, `StateGraph`, `interrupt`, `Command`, `PostgresSaver`, `MemorySaver` (tests). Packages in `pyproject.toml`: `langgraph>=1.2.12`, `langgraph-checkpoint-postgres`, `langchain-openai`, `langchain-core`. **Risk**: fast-moving APIs. Mitigation: keep usage in few files, pin via `uv.lock`, and cover with tests (the agent's behaviour is tested with a fake model through the real graph).

### 15.2.5 FastMCP

The Python framework for the tool server (Chapter 8): `FastMCP(...)`, `@mcp.tool`, `custom_route`, `TokenVerifier` for auth, `Client` for the caller. **Version trap recorded**: FastMCP 4's client expects `httpx2` auth objects; `run()` takes `host=`/`port=`. The codebase depends on `fastmcp>=4.0.10`.

### 15.2.6 FastAPI, Starlette, uvicorn, Pydantic

FastAPI (built on **Starlette**, ASGI) with **Pydantic v2** for validation, `uvicorn` as the ASGI server (`--proxy-headers` and `FORWARDED_ALLOW_IPS` so it trusts Caddy's forwarded client address). Chapter 18.

### 15.2.7 PostgreSQL, psycopg 3, `psycopg_pool`

Chapter 17. The same database holds application tables, the audit log, and LangGraph's checkpoint tables.

### 15.2.8 PyJWT, `cryptography`, `argon2-cffi`

`pyjwt[crypto]` signs and verifies RS256 tokens; `cryptography` loads PEM keys and generates key pairs (`scripts/generate_jwt_keys.py`); `argon2-cffi` hashes passwords with Argon2id. Chapter 20.

### 15.2.9 prometheus_client

Defines counters/gauges/histograms and renders the exposition text (Chapter 13).

### 15.2.10 Next.js, React, TypeScript, Vitest

The UI (Chapter 19); `vitest` runs the stream-parser tests; `tsc --noEmit` type-checks. `apps/web/AGENTS.md` carries a warning that this Next.js version has **breaking changes from what models were trained on and to read the bundled docs in `node_modules/next/dist/docs/`** before writing code: a modern hazard worth noticing: *AI assistants' knowledge of fast-moving frameworks goes stale; read the version's own documentation.*

### 15.2.11 Mastra (TypeScript)

**What.** An open-source **TypeScript framework for building AI applications**: **agents** (LLM + tools + memory), **workflows** (typed, step-based, with suspend/resume), **tools**, **RAG and memory** helpers, **evals/scorers**, **observability** (tracing with pluggable exporters), pluggable **storage**, and a local development UI called **Studio** (`mastra dev`, port 4111).

**How it is used here** (`apps/mastra`, Mastra 1.x: `@mastra/core`, `@mastra/evals`, `@mastra/libsql`, `@mastra/observability`, `@mastra/otel-exporter`, `zod`):

| Mastra concept | Use here |
|---|---|
| `Mastra` instance | holds storage, observability, scorers and workflows (`mastra/index.ts`) |
| `createWorkflow` / `createStep` (+ `.then().commit()`) | the `stylistSession` workflow with one step `converse`, typed with **zod** schemas |
| **Scorers** (`createScorer`...) | 12 scorers wrapping the pure rules; attached to the step with 100% sampling |
| **Observability** | `Observability({ configs: { default: { serviceName, exporters }}})` with exporters: `MastraStorageExporter` (traces/scores for Studio), the custom **`AuditExporter`** (a `BaseExporter` subclass writing to the hash chain), and optionally `OtelExporter` (OTLP to Jaeger) |
| **Storage** | `LibSQLStore` (a SQLite-compatible file `.data/mastra.db`) |
| **Studio** | browse workflows, traces, scores at http://localhost:4111 |

**Decision recorded: Mastra as a *gateway* was skipped.** The original plan had a TypeScript Mastra layer between the UI and the Python API. It was dropped: **the UI talks to the API directly**, because a gateway would add a hop, a second auth boundary and a second place for logic without solving a problem the project had. Mastra stayed for what it does well *here*: **tracing, scorers and workflow-driven evals**. This is an exemplary FDE decision: *evaluate a tool on the problem in front of you, keep the useful part, drop the rest.*

**Notes and honest limits.** Mastra's libSQL storage does not persist Mastra's own metrics or logs (it says so at startup); the `engines` field requires Node ≥ 22.18; the workflow drives the real API over HTTP rather than calling Python code (a cross-language boundary by design).

### 15.2.12 Infrastructure tools

* **Docker, Docker Compose, Caddy**: Chapters 25-27.
* **Jaeger, Prometheus, Grafana**: Chapter 13.
* **uv** (fast Python package/project manager, lockfile `uv.lock`; `uv run`, `uv sync --frozen`), **npm workspaces**, **pytest**, **ruff**, **vitest**, **TypeScript**.
* **Playwright** (browser automation) was used for an end-to-end test in Edge during development (Chapter 29).

## 15.3 Evaluating a third-party service (the FDE checklist)

Before depending on any external service:

**Technical**
* [ ] API stability and versioning policy; deprecation notices; changelog.
* [ ] Does it support what you need (features, structured output, streaming, regions)?
* [ ] Latency and reliability (status page history, SLA, rate limits, quotas).
* [ ] SDK quality; raw HTTP escape hatch.
* [ ] Sandbox/test mode, free tier for CI.
* [ ] Observability: request ids, usage endpoints, logs.

**Commercial**
* [ ] Pricing model (per call, per token, seat, minimum commit), overage behaviour, *price changes*.
* [ ] Free-tier terms: can you rely on it? (Free tiers vanish or throttle.)
* [ ] Contract, support tiers, vendor viability.

**Security and legal**
* [ ] **Data handling**: is your data stored, logged, used for training, retained for N days? Region/residency? Sub-processors?
* [ ] Compliance (SOC 2, ISO 27001, GDPR/DPA, India DPDP Act, HIPAA if relevant).
* [ ] Authentication model; key scoping and rotation.
* [ ] Terms of service for your use (caching results, commercial use, scraping, automated access).
* [ ] Incident history and disclosure policy.

**Strategic**
* [ ] **Lock-in** (proprietary formats, embeddings, prompts, features) and **exit path**.
* [ ] Can it be replaced behind an adapter within days?
* [ ] Open-source alternatives and self-hosting option.

Record the answers in a short **decision record** (an ADR): context, options, decision, consequences. Appendix D and the project's notes show the style.

## 15.4 Integration patterns that keep you safe

1. **Adapter / port-and-adapter (anti-corruption layer).** One module per vendor translating their shapes to your domain types (`providers/serpapi.py`, `llm.py`). The rest of the code never sees vendor JSON.
2. **Typed boundary**: parse vendor responses into Pydantic models immediately; reject surprises there.
3. **Contract tests with recorded fixtures.** Save real responses (`tests/fixtures/serpapi_*.json`) and test your parser against them; refresh periodically to detect upstream format drift. Pair with a **small live smoke test** you run manually.
4. **Timeouts, bounded retries with backoff, and clear error mapping** (`UpstreamError(retryable=...)`).
5. **Caching** where terms allow, with TTL and bounds.
6. **Fakes** for offline development (`mock_search`, `ScriptedLLM`).
7. **Feature flags and fallbacks** when a vendor is down.
8. **Secrets management**: keys in env vars/secret stores, per-environment, scoped, rotated; never in git or front-end code.
9. **Budgets and kill switches** for paid APIs (Chapter 14).
10. **Pin versions** (lockfile) and read changelogs before upgrades; run evals after.
11. **Idempotency and webhooks vs polling** when integrating asynchronous vendors (verify webhook signatures; make handlers idempotent).
12. **Document the integration**: what it does, limits, credentials, how to test, how to replace. (This repo's `docs/mcp-guide.md` does exactly this.)

## 15.5 A framework-selection mini-guide

| If your situation is... | Consider |
|---|---|
| One model call and some validation | Provider SDK + Pydantic; no framework |
| Several steps, branching, human approval, durable state | LangGraph (or a workflow engine like Temporal if business-critical) |
| TypeScript-first team, want agents + workflows + evals in one box | Mastra, Vercel AI SDK |
| RAG over documents, many loaders and indexes | LlamaIndex, Haystack |
| Strongly typed, Pythonic agents | Pydantic AI |
| Automatic prompt optimisation against a metric | DSPy |
| Heavy Microsoft/.NET ecosystem | Semantic Kernel |
| You want a vendor's batteries-included agent runtime | that vendor's Agents SDK / hosted agents |
| Customer says "no new dependencies" | plain Python or TypeScript with a thin HTTP client (be able to write the tool-calling loop by hand: Chapter 9) |

## Common mistakes

* Adopting a framework for one feature and importing its concepts everywhere.
* Letting vendor response shapes leak through the codebase.
* Treating a free tier as production capacity.
* Not reading the data-retention and ToS terms.
* No fixtures: integration tests that need the network and credits.
* Assuming a model/gateway supports a feature because another model does.
* Upgrading AI libraries without reading changelogs or re-running evals.

## Summary

* The ecosystem has layers: providers, gateways, orchestration, protocols, retrieval, data APIs, evals/observability, guardrails, hosting. Place each new tool in a layer.
* This project: OpenRouter (and optionally OpenCode Zen) for models, SerpAPI for products, LangGraph for the agent, FastMCP for tools, Postgres for state, Mastra for evals/tracing, Prometheus/Grafana/Jaeger for observability, Docker/Caddy for deployment.
* Evaluate services on technical, commercial, security and strategic criteria; record decisions.
* Integrate behind adapters with typed boundaries, fixtures, timeouts, retries, budgets and fallbacks.

## Key terms

*gateway, OpenAI-compatible, model slug, free tier, rate limit, adapter, anti-corruption layer, contract test, fixture, vendor lock-in, ADR, data retention, sub-processor, DPA, Mastra, Studio, scorer, exporter.*

## Interview questions

1. What is an LLM gateway like OpenRouter? Pros and cons versus calling vendors directly.
2. How would you decide whether to adopt a new AI framework for a project?
3. How do you protect your code from a vendor's API changing?
4. What would you check about a vendor's data policy before sending customer data to it?
5. Why did this project skip the Mastra gateway but keep Mastra?
6. What are the risks of building on a free tier?

## Exercises

1. Write an ADR (one page) for "use SerpAPI for product search" including alternatives, risks (ToS, cost), and an exit plan.
2. Add a second search provider adapter (a fake "catalogue" provider) behind the same interface and switch with a config value; prove with tests that the agent code did not change.
3. Compare three models on the project's eval set through OpenRouter: table of quality, latency and cost.
4. Read the changelog of one dependency (LangGraph or FastMCP) and list changes that could break this repo.
5. Draw the layer map for a customer scenario of your choice (support bot over PDFs) and fill each layer with a concrete product choice and an alternative.
