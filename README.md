# AI Stylist

A chat app for **menswear in India**. You say the occasion and your budget; it suggests styles; you pick
one; it finds 4 top + bottom outfits from Indian stores (Myntra, Amazon.in, Flipkart, AJIO...) with
photos, prices and buy links. Every product is checked against what was asked for before it is shown.

```
Browser (Next.js)                       apps/web
   │  HTTPS, short-lived login token + HttpOnly refresh cookie
   ▼
API  (FastAPI + LangGraph agent)        services/api      ──►  Postgres (users, conversations, outfits, audit log)
   │  a fresh single-use signed token on EVERY request
   ▼
MCP tool server (private, no public address)   services/mcp   ──►  Tavily search over 100 approved menswear stores
```

The agent decides *what* to look for (LLM). The tool server *finds* products. A rule-based verifier decides
whether a product really matches (price, garment, colour, men's, neckline...) and is never skipped.

## How a conversation works

The conversation never ends. Every message, typed or a clicked style card, goes through a router that reads the
saved state (what was asked, which styles were offered, which outfits were shown) and continues from the right
step: answer a missing detail, pick or describe a style, **refine** shown outfits ("cheaper", "more like outfit 3,
but make the bottom purple, under 1500"), change the budget or occasion, ask a question, or start a new request.
A refinement is turned into a structured edit; code (not the model) resolves "the 3rd one", works out the new
budget, and applies the change to the search. The planner chooses colours itself for coordination and never shows
them; a colour you ask for is searched, checked and shown. There are no usage limits unless you configure some.

## Run it locally

Needs: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node 22+, Docker.

```bash
cp .env.example .env                       # then fill in your keys (see the file's comments)
uv run --project services/mcp python scripts/generate_jwt_keys.py     # creates the signing keys in .env
docker compose up -d postgres              # the database

# three terminals:
(cd services/mcp && uv sync && uv run python -m mcp_server.server)           # tool server  :8001
(cd services/api && uv sync && uv run uvicorn api.main:app --port 8000)     # API          :8000
npm install && npm run dev -w apps/web                                       # web app      :3000
```
Open http://localhost:3000, create an account, ask for "college wear, around ₹4000".

**Everything in containers** (the way it will be hosted): `docker compose up -d` starts Postgres, the private
tool server and the API. The tool server publishes **no port**, so only the API can reach it.

## Tests

```bash
(cd services/api && uv run pytest -q && uv run ruff check .)     # agent, verifier, accounts, HTTP API, audit log
(cd services/mcp && uv run pytest -q && uv run ruff check .)     # tools, auth, limits, link safety
(cd apps/web && npm test && npm run typecheck)                   # stream parser, types
```
The API tests use a real, throwaway Postgres (they skip if Docker's Postgres is not running).

## Deploying

`docker-compose.prod.yml` is the hosted layout (one public door, everything else private), runnable on your
laptop first and then on a small server. Guide: [docs/deploy.md](docs/deploy.md).

## Evals, tracing, audit, observability (all local)

Built with Mastra in `apps/mastra`, plus Jaeger, Prometheus and Grafana in Docker. Full guide: [docs/observability.md](docs/observability.md).

```bash
python scripts/init_observability.py && docker compose --profile observability up -d
npm run eval                # plays 17 shopper sessions (4 of them keep talking after the outfits) through a traced workflow, 13 scorers
npm run audit:verify        # checks the hash-chained audit record for tampering
npm run studio              # Mastra Studio: http://localhost:4111  (Jaeger :16686, Grafana :3001)
(cd apps/mastra && npm test && npx tsc --noEmit)
```

## Security, in one page

| Layer | What it does |
|---|---|
| Tool server has no public address | Only the API can reach it (containers: no published port) |
| Signed, short-lived, **single-use** tokens | The API signs each request (RS256); the tool server verifies with the public key and refuses a replayed token |
| Host / Origin check | A web page in a browser cannot reach the local server (DNS rebinding) |
| Per-user rate limits + daily credit caps | A bug or a stolen token can waste only a small, known amount |
| `check_link` safety | https only, allow-listed stores, public addresses only, connects to the address it checked |
| Accounts | Argon2id password hashes, 15-minute access tokens, rotating refresh tokens with theft detection, login lockout |
| Ownership checks | You can only read your own conversations and open buy links for products you were shown |
| Audit log | Append-only and **hash-chained**: tampering is detectable (`GET /admin/audit/verify`) |
| Hardened containers | Non-root, read-only filesystem, all Linux capabilities dropped, no secrets in images |
| Secret hygiene | `.env` is git-ignored; a test fails if a real secret appears in `.env.example` |

## Where things are

| Path | What |
|---|---|
| `services/api/src/api/agent/` | the LangGraph agent, the verifier (`verify.py`), `find.py`, the MCP search client |
| `services/api/src/api/routes/` | auth, chat (streamed), buy links, admin |
| `services/api/migrations/` | the database schema as plain, numbered SQL |
| `services/mcp/src/mcp_server/` | the tool server: tools, auth, limits |
| `prompts/stylist/` | the agent's prompts, versioned |
| `docs/mcp-guide.md` | step-by-step guide to the tool server |
| `docs/tools-reference.html` | every tool's input/output schema and workflow |

## Not built yet
- **"Try it on me"** (photos, character sheet, try-on images): waiting on a decision about the image provider.
- **Mastra gateway**: skipped. The web app talks to the API directly. `apps/mastra` is the evals/tracing/audit
  app (below), not a gateway.
- A model-based (or human) judge of outfit taste, log search (Loki), and a hosted deployment.
