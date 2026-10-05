# Evals, tracing, audit and observability

Everything here runs on your own machine. Nothing is sent to a third party.

## The five pieces and what each answers

| Piece | Where | Question it answers |
|---|---|---|
| **Traces** | Mastra Studio, Jaeger | "What happened in THIS request, step by step, and how long did each step take?" |
| **Evals** | `apps/mastra` (scorers, dataset) | "Does the system still keep its promises? Did a change make it better or worse?" |
| **Audit** | Postgres + Mastra's chain | "Who did what, and can I prove nobody edited the record?" |
| **Metrics** | Prometheus, Grafana | "How is the system doing overall, over time?" |
| **Logs** | `docker compose logs`, one JSON object per line | "What exactly was said when it went wrong?" |

One id ties the first four together: the **trace id**. Mastra creates it, sends it to the API
(`traceparent` header), and the API writes it into its logs and its audit-log entries. Paste a trace id
into Jaeger to see the steps; search the audit log for it to see what was recorded for that request.

## Start everything

```bash
python scripts/init_observability.py               # once: creates the token Prometheus uses for /metrics
docker compose up -d postgres
docker compose --profile observability up -d       # Jaeger, Prometheus, Grafana (127.0.0.1 only)

# the API. demo mode is free and instant; live uses real model credits
(cd services/api && BACKEND_MODE=demo uv run uvicorn api.main:app --port 8000)

npm run studio                                      # Mastra Studio  http://localhost:4111
```

| UI | Address | You will see |
|---|---|---|
| Mastra Studio | http://localhost:4111 | workflows, traces, eval scores |
| Jaeger | http://localhost:16686 | traces (service `stylist-mastra`) |
| Grafana | http://localhost:3001 | dashboard "AI Stylist overview" (anonymous viewer) |
| Prometheus | http://localhost:9090 | raw metrics and targets |

## Evals

```bash
OTEL_TRACES_ENDPOINT=http://localhost:4318/v1/traces npm run eval -- --concurrency 3
npm run eval -- --only college-4000,missing-budget
```

Each case plays a whole shopper session through the traced workflow `stylistSession`, then 13 scorers
judge it. **Hard guarantees (gates, must be 1.0 for every case, exit code 1 otherwise):** four outfits,
within budget, every item verified, menswear only, no duplicates, correct totals, asks only for what was
missing, no errors, different tops and bottoms across the outfits (variety), and follow-up messages handled
(a reply to every one; change requests deliver new, in-budget, never-repeated outfits). **Soft signals (reported, never fail the run):** that no explanation spells out a colour, speed, number of model calls and searches.

The same scorers are attached to the workflow step, so Mastra scores every run as it finishes and the
scores appear in Studio and in the audit chain. Cases live in `apps/mastra/src/evals/cases.ts`.

**What demo mode does and does not prove.** It uses a scripted stand-in for the model and mock products,
so a perfect score proves the plumbing (budget enforcement, verification, streaming, database,
rate limits, tracing) and nothing about whether the REAL model makes good outfits. To evaluate the real
model, run against `BACKEND_MODE=live`: a full run is ~6 model calls per case (a few more with follow-ups), so 17 cases need ~110 calls
(the free model allows 50 a day). Judging taste (does this outfit look good?) needs a model-based or human
scorer; none is built yet.

## Audit

There are two hash-chained, append-only records, deliberately separate:

* **Postgres `audit_log`** (the Python API): accounts, logins, messages sent (length only, never the
  text), outfits delivered, buy links. Verify: `GET /admin/audit/verify` as an admin.
* **Mastra `audit_chain`** (apps/mastra/.data/audit.db): every finished workflow run, step, tool call,
  model generation and scorer run, plus every eval score. It records ids, names, outcome, duration and
  SHA-256 fingerprints of inputs and outputs, never the inputs and outputs themselves.
  Verify: `npm run audit:verify` (exit code 1 if tampering is found).

Each entry stores the hash of the one before it, so editing or deleting any entry breaks every later
hash. **Honest limit:** someone with full control of a database file could rewrite the whole chain
consistently. Tamper evidence is only as strong as a copy of the latest hash kept somewhere else. Before
relying on this for anything serious, periodically write the newest hash to a place the database admin
cannot edit.

## Metrics

Prometheus reads `/metrics` from the API and the tool server with a bearer token
(`METRICS_TOKEN`; empty means the endpoint is off). Metrics hold only names and numbers: no user ids, no
message text, no product data, and tests check that. The dashboard has three rows: shopper experience,
cost and dependencies, health and security.

## Known limits

* Mastra's libSQL storage does not store Mastra's own metrics or logs (it says so at startup). Prometheus
  and the JSON logs cover that, so nothing is lost; it is only the Studio "metrics" tab that stays empty.
* The tool-server panels stay empty in demo mode (demo bypasses the tool server).
* A rate-limit wait shows up in a trace as an unexplained gap between stages; it is not labelled yet.
* Logs are plain JSON lines in the container output; there is no log search UI (Loki is the usual next step).
* Grafana's admin password defaults to a placeholder: set `GRAFANA_ADMIN_PASSWORD` before anything but
  local use. Its port is bound to 127.0.0.1 so nobody else can reach it.
