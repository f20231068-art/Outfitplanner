# Chapter 13. Observability: Logs, Metrics, Traces

> **Learning objectives.** Explain the three pillars (logs, metrics, traces) and what question each answers; instrument a Python service with structured logs, Prometheus metrics and trace ids; understand OpenTelemetry and W3C trace context; design dashboards, SLIs, SLOs and alerts; handle AI-specific signals (tokens, cost, quality); keep telemetry private; and read `api/telemetry.py`, the `/metrics` endpoints, the Prometheus/Grafana/Jaeger stack and the trace-id propagation in this repo.
>
> **Prerequisites.** Chapters 2, 9, 12.

---

## 13.1 Monitoring versus observability

**Monitoring** watches known failure modes ("alert if error rate > 5%"). **Observability** is the property that lets you *ask new questions of a running system without deploying new code* ("why was this one user's request slow at 14:03?"). You get it by emitting rich, correlated telemetry. It matters more for AI systems than for ordinary ones because:

* **Behaviour is non-deterministic**: the only way to understand a bad outcome is to see what actually happened in that run.
* **There are many external dependencies** (model, search, tools) with their own latency and failure.
* **Cost is per call**: you must see spend and call counts per feature.
* **Quality** drifts silently when a provider updates a model.

### The five pieces (from this repo's `docs/observability.md`)

| Piece | Question | Where |
|---|---|---|
| **Traces** | What happened in THIS request, step by step, and how long did each step take? | Mastra Studio, Jaeger |
| **Evals** | Does the system still keep its promises? Did a change make it better or worse? | `apps/mastra` |
| **Audit** | Who did what, and can I prove nobody edited the record? | Postgres + Mastra chain |
| **Metrics** | How is the system doing overall, over time? | Prometheus, Grafana |
| **Logs** | What exactly was said when it went wrong? | container output (JSON lines) |

One id, the **trace id**, ties the first four together: Mastra creates it, sends it to the API (`traceparent` header), and the API writes it to logs and audit entries.

## 13.2 Logs

A **log** is a timestamped record of an event. Logs give *detail* about specific events; they are poor for trends and expensive at volume.

### Structured logging

Plain text lines ("User 42 failed to log in") are hard to query. **Structured logs** emit one **JSON object per line** with named fields; log platforms can then filter and aggregate (`level=ERROR trace_id=...`). The repo's `JsonFormatter`:

```python
class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {"ts": ..., "level": record.levelname, "logger": record.name, "msg": record.getMessage(),
                 "request_id": request_id_var.get(), "trace_id": trace_id_var.get()}
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)     # the stack trace stays ONE line of JSON
        return json.dumps(entry, ensure_ascii=False)
```

Notice: `json.dumps` also **escapes newlines inside messages**, which prevents **log injection** (an attacker putting "\nERROR admin logged in" into an input to forge entries) and keeps one event per line.

### Levels

`DEBUG` (developer detail), `INFO` (normal events), `WARNING` (unexpected but handled: a refused token, a retry), `ERROR` (failed operation), `CRITICAL` (service-threatening). Production usually runs at INFO; raise to DEBUG temporarily and *never* leave sensitive debug logging on.

### Correlation ids and `contextvars`

To follow one request through many log lines you attach an id. Passing the id through every function is tedious; instead use **context variables**:

```python
request_id_var = contextvars.ContextVar("request_id", default="-")
...
request_id_var.set(request_id)         # in the middleware, once per request
...
request_id_var.get()                   # in the formatter, for every line, anywhere
```

`ContextVar`s are the async-safe replacement for thread-locals: each asyncio task (and each request) sees its own value. **Caveat worth knowing**: context does not automatically cross into threads you start yourself with `ThreadPoolExecutor` (unlike `asyncio.to_thread`, which copies it), so log lines emitted from the *parallel search worker threads* may show `request_id: "-"` unless you run the work under `contextvars.copy_context().run(...)`. Whenever you hand work to a thread pool, decide whether the context should follow it.

### What never goes in logs

* **Secrets**: passwords, tokens, API keys. (`httpx`'s logger is set to `WARNING` because its INFO lines contain request URLs, and the search URL contains the API key. `uvicorn.access` is also silenced because the app logs requests itself, with route *templates*.)
* **Personal content**: message text, product details tied to a user, emails. The audit log records message *length*, and the login audit stores a **12-character hash tag** of the email, not the email.
* **Raw request bodies.**

A **logging policy** (what we log, what we never log, retention) is a design decision, written down, and enforced by tests (`test_log_lines_are_json_and_carry_the_ids_but_nothing_else_sensitive`).

### Where logs go

Twelve-factor apps write logs to **stdout**; the platform collects them (`docker compose logs -f api`; in production Loki, Elasticsearch, CloudWatch, Datadog, Cloud Logging). This repo stops at "JSON lines in container output"; it names Loki as the usual next step and lists "no log search UI" as a known limit.

## 13.3 Metrics

A **metric** is a number tracked over time, aggregated cheaply. Metrics are great for **trends, dashboards and alerts**, and tell you *that* something is wrong, not *why*.

### Metric types (Prometheus)

| Type | Meaning | Example | Query pattern |
|---|---|---|---|
| **Counter** | only goes up (resets on restart) | requests, errors, LLM calls | `rate(x_total[5m])` |
| **Gauge** | goes up and down | active chat turns, queue length, memory | the value, `max_over_time` |
| **Histogram** | counts observations in buckets (+ sum, count) | request/LLM/chat-turn durations | `histogram_quantile(0.95, rate(x_bucket[5m]))` |
| **Summary** | client-side quantiles | rarely preferred (cannot be aggregated across instances) | |

### Labels and cardinality (the most important metrics skill)

Labels add dimensions (`method`, `route`, `status`). **Every unique combination of label values is a separate time series** that costs memory and money. **High-cardinality labels** (user ids, emails, raw URLs, trace ids, product ids) can explode a metrics system and also **leak personal data**. The repo's rules:

* The HTTP metric labels `route` with the **route template** (`/conversations/{conversation_id}`), never the real path: in `main.py`, `template = getattr(route, "path", "unmatched")`. Bounded cardinality and no ids in metric data.
* The tool server's metrics docstring: *"Numbers and names only: never arguments, product data, user ids, tokens or keys, so scraping it cannot leak anything about shoppers."*
* Unmatched paths collapse to `"unmatched"` so a scanner hitting a million random URLs cannot create a million series.

### The metrics in this repo

API (`api/telemetry.py`):

| Metric | Type | Labels | Meaning |
|---|---|---|---|
| `stylist_http_requests_total` | counter | method, route, status | request volume and errors |
| `stylist_http_request_seconds` | histogram | route | request latency |
| `stylist_chat_turns_total` | counter | outcome (`ok`, `waiting_for_user`, `no_outfits`, `error`) | turn results |
| `stylist_chat_turn_seconds` | histogram | | time to finish a turn |
| `stylist_stage_seconds` | histogram | stage | time per agent node |
| `stylist_outfits_delivered_total` | counter | | outfits shown |
| `stylist_outfits_by_confidence_total` | counter | confidence | quality mix (high vs low) |
| `stylist_llm_calls_total`, `stylist_llm_call_seconds` | counter, histogram | | model usage and latency |
| `stylist_product_searches_total` | counter | | search volume |
| `stylist_logins_total` | counter | outcome | login success, failure, lockout |
| `stylist_rate_limited_total` | counter | limiter | which limiter refused |
| `stylist_active_chat_turns` | gauge | | concurrency right now |
| `stylist_buy_links_total` | counter | outcome | *defined, but not incremented anywhere yet* |

Tool server (`mcp_server/metrics.py`): `mcp_tool_calls_total{tool,outcome}` (outcome `ok`/`refused`/`error`), `mcp_tool_seconds{tool}`, `mcp_cache_total{tool,result}`, `mcp_search_credits_spent_total{kind}`, `mcp_limit_hits_total{limit}`, `mcp_auth_refusals_total{reason}`.

Two honest observations an interviewer would love: (1) **`BUY_LINKS` exists but `routes/products.py` never calls it**, so a Buy-link panel built on it would stay empty; *defined metrics that nobody increments are a classic instrumentation bug, caught only by checking the dashboard against reality.* (2) The metric `stylist_llm_calls_total` counts *calls* but nothing records **tokens**, so you cannot compute spend; adding `usage` token counters from the model response is the obvious next step for cost observability.

### The `tracked()` context manager

```python
@contextmanager
def tracked(tool):
    start = time.perf_counter(); outcome = "ok"
    try:    yield
    except ToolError: outcome = "refused"; raise      # a deliberate refusal
    except Exception: outcome = "error";   raise      # a bug
    finally:
        TOOL_CALLS.labels(tool, outcome).inc()
        TOOL_SECONDS.labels(tool).observe(time.perf_counter() - start)
```

A reusable instrumentation point that **separates expected refusals from bugs**: an alert on `outcome="error"` is meaningful; one on `refused` would be noise.

### Pull model, scraping, and `/metrics`

Prometheus **pulls**: every `scrape_interval` (10 s here) it fetches `/metrics` (a plain-text exposition format) from each target. Targets are listed in `prometheus.yml` (`api:8000`, `mcp:8001`, and `host.docker.internal:8000` for an API run directly on the laptop). Both services guard `/metrics`:

```python
token = request.app.state.cfg.metrics_token
if not token: return 404                                          # OFF unless a token is configured
sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
if not hmac.compare_digest(sent.encode(), token.encode()): return 401   # constant-time comparison
```

The token is delivered to Prometheus as a **Docker secret file** (`credentials_file: /run/secrets/metrics_token`), never in the compose file. In the hosted layout `/metrics` is not routed by Caddy at all, so it is unreachable from the internet.

### Method: what to measure

* **RED** (for request-driven services): **R**ate, **E**rrors, **D**uration.
* **USE** (for resources): **U**tilisation, **S**aturation, **E**rrors.
* Google SRE's **four golden signals**: latency, traffic, errors, saturation.
* For AI systems add: **model calls and tokens**, **cost**, **tool error rates**, **cache hit rate**, **validation-retry rate**, **replan rate**, **confidence/quality mix**, **refusals**, **time per stage**.

### PromQL you should be able to write

```promql
# requests per second by route over 5 minutes
sum by (route) (rate(stylist_http_requests_total[5m]))

# 5xx error ratio
sum(rate(stylist_http_requests_total{status=~"5.."}[5m])) / sum(rate(stylist_http_requests_total[5m]))

# p95 chat-turn latency
histogram_quantile(0.95, sum by (le) (rate(stylist_chat_turn_seconds_bucket[5m])))

# share of outfits with low colour confidence
sum(rate(stylist_outfits_by_confidence_total{confidence="low"}[1h])) / sum(rate(stylist_outfits_delivered_total[1h]))

# search credits burned today (approximate)
increase(mcp_search_credits_spent_total[24h])

# who is hitting limits
sum by (limiter) (increase(stylist_rate_limited_total[1h]))
```

Remember: `rate()` for counters; never graph a raw counter; `histogram_quantile` needs the `_bucket` series and `by (le)`.

### Dashboards as code

Grafana is configured by **provisioning files**, not clicks: `grafana/provisioning/datasources/datasources.yml` (Prometheus uid `prometheus`, Jaeger uid `jaeger`), `provisioning/dashboards/dashboards.yml`, and the dashboard JSON `dashboards/stylist.json` ("AI Stylist overview") with three rows: **shopper experience**, **cost and dependencies**, **health and security**. Because they live in git, every developer gets the same dashboards and changes are reviewed. Grafana's admin password comes from `GRAFANA_ADMIN_PASSWORD`; anonymous access is Viewer-only; the port is bound to `127.0.0.1`.

**Dashboard design tips:** start with the user's experience (is it working? how fast?), then dependencies (model, search, database), then saturation and cost; avoid 40 panels; label units; use the same time range; link panels to traces and logs; put an "annotation" on every deployment.

## 13.4 Traces

A **trace** records the path of a *single request* through the system as a tree of **spans**. A span has a name, start time, duration, attributes (key-values), a parent span, and status. A trace answers *where did the time go?* and *which step failed?*

```
trace 4bf92f35...                                   (the whole conversation turn: 31.2 s)
├─ backend: gather_prefs         1.8 s
├─ backend: propose_styles       2.4 s
└─ ...
   ├─ backend: plan_outfits      3.9 s   (model call)
   ├─ backend: find_products    21.7 s   (8 parallel searches + verification)
   └─ backend: rank_and_validate 0.01 s
```

### Context propagation and W3C Trace Context

For a trace to span *services*, each hop must pass the **trace context** to the next. The standard is the **W3C `traceparent` header**:

```
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
             ^^ ^-------- trace id (32 hex) ---^ ^- parent span id (16 hex) -^ ^^ flags (01 = sampled)
             version
```

In this repo, the Mastra eval harness builds a `traceparent` from its own trace id; the API's middleware calls `parse_trace_id`, which validates with a strict regex (`^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$`), rejects the all-zero id, falls back to an optional `X-Trace-Id`, and otherwise **generates its own**. A malformed header is "never trusted, never echoed". The API then returns `X-Request-ID` and `X-Trace-Id` response headers, writes the trace id into JSON logs and audit entries, and includes it in the SSE `done` event. **Never trust a client-supplied id blindly**: validate its shape (so a hostile header cannot inject log content), and never use it for security decisions.

### The `request_id` versus the `trace_id`

* `request_id`: made by the API per HTTP request (16 hex): unique to this service's request.
* `trace_id`: may come from the caller; spans multiple requests/services (a whole conversation turn, or a whole eval case with several turns).

### OpenTelemetry (OTel)

**OpenTelemetry** is the vendor-neutral standard for generating traces, metrics and logs: **APIs and SDKs** per language, **instrumentation libraries** (auto-instrument FastAPI, httpx, psycopg), the **OTLP** wire protocol, and the **Collector** (a pipeline that receives, processes and exports telemetry to any backend). Backends: Jaeger, Tempo, Zipkin, Honeycomb, Datadog, Grafana Cloud, and many more.

Minimal Python usage:

```python
from opentelemetry import trace
tracer = trace.get_tracer("stylist-api")

with tracer.start_as_current_span("find_products") as span:
    span.set_attribute("specs.count", 4)
    ...                                     # child spans created inside nest automatically
```

Key concepts: **sampling** (head-based: decide at the start, e.g. 10%; tail-based: keep slow/error traces), **attributes** (searchable data; follow semantic conventions), **span events**, **links**, **baggage** (propagated key-values), and **exporters** (Mastra's `OtelExporter` sends OTLP/HTTP protobuf to Jaeger on `:4318`).

### How this repo traces

Tracing here is **client-driven** (a deliberate, interesting design): the *evaluation workflow* creates the trace; the API does not emit its own spans yet. The API reports each stage with `status` events including `duration_ms`; Mastra turns each into a **child span back-dated by that duration** (`startTime: now - duration`), so the trace shows true step lengths without instrumenting the backend with an OTel SDK. Advantages: simple, no new backend dependency. Limits: only traces driven by the harness exist (real user traffic produces logs/metrics/audit with trace ids but not full spans); finer-grained spans (database, each model call, each tool call) are missing. **The production-grade next step is auto-instrumentation inside the API and the tool server (FastAPI, httpx, psycopg) exporting OTLP**, with the same trace-id propagation already in place.

### Tracing LLM applications specifically

Beyond generic spans, LLM traces should capture: the **prompt version**, model name and parameters, **input/output token counts**, latency (time to first token and total), the **tool calls** and their results, retries/validation errors, and **cost**. Platforms specialised for this: **Langfuse, LangSmith, Arize Phoenix, Helicone, Braintrust, Datadog LLM Observability**, and the **OpenTelemetry GenAI semantic conventions** that standardise attribute names. **Privacy warning:** prompts and outputs usually contain user data; decide whether to store them, redact, hash or sample (this repo stores *fingerprints*, i.e. SHA-256 prefixes of inputs/outputs in the audit chain, not the content).

### Debugging story (put it all together)

> *A user says: "At 14:03 I asked for office wear and got only 2 outfits."*

1. Find the user's conversation id; look up audit entries (`message_sent`, `outfits_delivered`) around 14:03: you get the `trace_id` and `count: 2`.
2. Search logs by `trace_id`: you see `WARNING MCP search failed (try 1/2): ReadTimeout` and a retry.
3. In Jaeger or Mastra Studio, open the trace: `find_products` took 29 s; stage timings show a rate-limit wait gap.
4. In Grafana at 14:03: `mcp_limit_hits_total{limit="daily_credits"}` jumped; `stylist_chat_turns_total{outcome="no_outfits"}` ticked.
5. Conclusion: the daily credit cap was hit; confirm by `increase(mcp_search_credits_spent_total[24h])` ≈ the global cap. Fix: raise the cap or inform the user better.

Metrics told you *something changed*; traces and logs told you *why*; the audit log gave you *who and when*, all linked by one id. That is observability.

## 13.5 SLIs, SLOs and alerts

* **SLI**: a measured indicator of good service. For this app: *conversation turns completing without error* (`outcome != "error"`), *p95 turn time*, *fraction of turns that deliver ≥ 1 outfit*, *buy-link `live` rate*.
* **SLO**: the target for an SLI over a window: *"99% of turns succeed over 30 days"*.
* **Error budget**: `1 - SLO` (1% of turns may fail); spending it on releases and experiments is acceptable; exhausting it pauses risky changes.

**Good alerts** are **symptom-based** (users are affected: error ratio, latency, no outfits), **actionable** (a human can do something), **linked to a runbook**, and **rare**. Alert on **burn rate** (how fast the error budget is being consumed) rather than raw thresholds. Distinguish **page** (wake someone: outage) from **ticket** (look tomorrow: cost creeping). Avoid alerting on causes (CPU 80%) unless they predict symptoms. Example rule:

```yaml
groups:
  - name: stylist
    rules:
      - alert: HighChatErrorRatio
        expr: |
          sum(rate(stylist_chat_turns_total{outcome="error"}[10m]))
            / sum(rate(stylist_chat_turns_total[10m])) > 0.05
        for: 10m
        labels: { severity: page }
        annotations:
          summary: "More than 5% of chat turns are failing"
          runbook: "docs/runbooks/chat-errors.md"
```

(Alert rules need Prometheus rule files and an **Alertmanager** that routes to email, Slack, or PagerDuty; this local stack does not configure alerts, an honest limit.)

## 13.6 Privacy and security of telemetry

Telemetry is a **data store** and a **leak path**:

* **Do not record secrets or personal content** (Section 13.2). Test it.
* **Protect `/metrics` and dashboards** (bearer token, private network, not routed publicly, anonymous Viewer only on localhost).
* **Limit retention** and who can query.
* **Cardinality is also a privacy control** (no user ids as labels).
* **Hash or truncate identifiers** you need only for grouping (12-char email tag; 32-char fingerprints).
* **Audit access** to production telemetry that could contain user content.
* Comply with deletion requests (traces and logs too).

## 13.7 The local observability stack in this repo

```bash
python scripts/init_observability.py                 # creates the token Prometheus uses (infra/observability/.secrets/metrics_token, git-ignored)
docker compose --profile observability up -d         # jaeger, prometheus, grafana
```

| Service | Image (pinned) | Port (127.0.0.1 only) | Notes |
|---|---|---|---|
| Jaeger | `jaegertracing/all-in-one:1.62.0` | 16686 (UI), 4318 (OTLP/HTTP in) | in-memory traces by default; `COLLECTOR_OTLP_ENABLED=true` |
| Prometheus | `prom/prometheus:v2.55.1` | 9090 | config mounted read-only; `metrics_token` Docker secret; `extra_hosts: host.docker.internal:host-gateway` to scrape an API running on the laptop |
| Grafana | `grafana/grafana:11.3.0` | 3001 → container 3000 | provisioned datasources and dashboard; anonymous Viewer; admin password from env |

Practices on display: **profiles** (opt-in services), **pinned image versions** (no `latest`), **volumes** for persistence (`promdata`, `grafanadata`), **bind to localhost** for admin UIs, **secrets via files**, **config as code**.

Known limits (from the docs): Mastra's libSQL storage does not store Mastra's own metrics/logs (Prometheus and JSON logs cover it); tool-server panels are empty in demo mode (demo bypasses the tool server); a rate-limit wait appears as an unexplained gap in a trace; no log search.

## 13.8 Going to production

* **Managed backends** are often cheaper than running your own: Grafana Cloud, Datadog, New Relic, Honeycomb, Sentry (errors), Better Stack, cloud-native (CloudWatch, Cloud Monitoring).
* **Error tracking** (Sentry) for exceptions with context and release tracking.
* **Uptime checks and synthetic monitoring**: a probe hitting `/health` from outside and a **scheduled end-to-end scenario**. *The eval harness is a ready-made synthetic monitor: run a tiny live case every hour and alert on failure.*
* **Sampling and retention policies** to control cost; **cardinality budgets**.
* **Alert routing** (Alertmanager/PagerDuty/Opsgenie), on-call rotation, runbooks.
* **Status page** and incident communication.
* **Cost dashboards** per feature/tenant: tokens, calls, search credits, infra.
* **Deployment markers** on graphs so regressions point to a release.

## Common mistakes

* Logging secrets or whole request bodies.
* High-cardinality labels (user ids, raw URLs).
* Metrics defined but never incremented (check dashboards against reality).
* Averages instead of percentiles; histograms with wrong buckets.
* Alerting on everything (alert fatigue) or nothing.
* Correlation ids not propagated across threads and services.
* Trusting client-supplied trace ids without validation.
* No cost or token telemetry for an AI feature.
* Observability added only after the first outage.

## Summary

* Observability = being able to ask new questions of a running system. Use logs (detail), metrics (trends), traces (path and time), plus audit (accountability) and evals (quality), linked by a trace id.
* Structured JSON logs with request and trace ids via `contextvars`; never log secrets or content.
* Prometheus counters, gauges, histograms; mind label cardinality; scrape a guarded `/metrics`; Grafana dashboards as code.
* W3C `traceparent` propagates trace context; OpenTelemetry is the standard; validate incoming ids.
* AI systems need extra signals: tokens, cost, retries, tool errors, cache hits, quality mix.
* Define SLIs/SLOs and alert on user-visible symptoms with runbooks.

## Key terms

*structured log, correlation id, contextvars, counter, gauge, histogram, label cardinality, scrape, PromQL, RED/USE, golden signals, trace, span, `traceparent`, OpenTelemetry, OTLP, collector, sampling, SLI, SLO, error budget, burn rate, runbook, synthetic monitoring.*

## Interview questions

1. Logs, metrics, traces: what does each answer? Give an example of using all three on one incident.
2. What is label cardinality and why does it matter? What are two ways this repo controls it?
3. Explain `traceparent`. How does this app link eval traces to API logs and audit entries?
4. How would you instrument tokens and cost for an LLM feature?
5. How do you design an alert that is actionable? What is a burn-rate alert?
6. What should never be logged?
7. Why does `contextvars` matter for request-scoped logging in async code? What can go wrong with threads?
8. How would you extend this stack for production?

## Exercises

1. Increment `BUY_LINKS` in `routes/products.py` for each outcome (`ok`, `dead`, `unverified`, `error`) and add a Grafana panel; write a test that the counter moves.
2. Add token counters (`stylist_llm_tokens_total{direction}`) by reading `usage_metadata` from model responses in `InstrumentedLLM`; compute cost per conversation in PromQL with an assumed price.
3. Wrap the worker-thread function in `find_products_for_specs` with `contextvars.copy_context().run` and prove log lines now carry the request id.
4. Add OpenTelemetry auto-instrumentation for FastAPI and httpx in the API, export OTLP to the local Jaeger, and compare with the Mastra-driven trace.
5. Write a Prometheus alert rule for the credit cap being near exhaustion, and a runbook explaining what to do.
