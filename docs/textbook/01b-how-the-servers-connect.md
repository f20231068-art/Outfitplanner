# Chapter 1b. How the Servers Are Built and Connected

> **Learning objectives.** Explain, for every server in this project, what it is, why it exists as a separate server, how it is started, how each pair of servers is connected (protocol, address, credentials, who initiates), and **why each environment file lives where it does and which variables each server receives**. You should be able to rebuild the whole multi-server system from an empty folder, in the right order, and verify each connection.
>
> **Prerequisites.** Chapter 1. Chapters 16, 20, 25, 26 give the background; this chapter is the *applied* wiring diagram of everything they teach.

> **Note on wording.** Docker calls each running piece a *service* (one container), and people loosely call them "servers". The application has **four servers of its own plus one front door** (on Railway the door moves *inside* the web service, giving exactly four services: section 1b.9): **Postgres** (data), **MCP tool server** (outside-world powers), **API** (brain and rules), **web** (UI server), and **Caddy** (the single public entrance). In the development setup, a sixth group (Jaeger, Prometheus, Grafana) is optional, and the Mastra evals app is a *client* that runs on your laptop.

---

## 1b.1 The servers at a glance

| Server | What it is | Technology | Listens on (inside Docker) | Reachable from outside the machine? | Holds which secrets |
|---|---|---|---|---|---|
| **postgres** | the database: users, conversations, outfits, audit log, agent checkpoints | `postgres:17` | 5432 | **No** in production (dev compose publishes 5432 for convenience) | its own password |
| **mcp** | the *tool server*: the only thing that talks to SerpAPI and fetches retailer pages | Python, FastMCP (`services/mcp`) | 8001 (`/mcp`, `/health`, `/metrics`) | **No** (never published, in dev or prod) | **public** JWT key, SerpAPI key |
| **api** | login, sessions, rate limits, the LangGraph agent, streaming chat, buy links, audit | Python, FastAPI (`services/api`) | 8000 | dev: yes (`8000:8000`); **prod: no** | **private** JWT keys, model key, DB URL |
| **web** | serves the Next.js UI files | Node, Next.js (`apps/web`) | 3000 | **No** in production (only through Caddy) | none |
| **caddy** | the single public door: HTTPS, routing | `caddy:2` | 80 and 443 | **Yes: the only published ports in production** | none (certificates in a volume) |

```
                      INTERNET
                         │  :80 / :443   (only these ports are open)
                         ▼
                    ┌─────────┐
                    │  caddy  │  routes by URL path
                    └──┬───┬──┘
        /auth /conversations /products /admin /health │   everything else
                 ┌─────┘                                └─────┐
                 ▼                                            ▼
            ┌─────────┐                                   ┌─────────┐
            │   api   │  (brain, rules, agent)            │   web   │  (UI files)
            └─┬─────┬─┘                                   └─────────┘
   SQL        │     │  signed single-use token per request
  (postgres:  │     ▼
   5432)      │  ┌─────────┐
              │  │   mcp   │  (private tool server)  ──► SerpAPI, retailer pages (internet)
              ▼  └─────────┘
        ┌──────────┐
        │ postgres │  (data)                      api ──► OpenRouter (the chat model, internet)
        └──────────┘
```

Two facts that surprise people and are worth stating clearly:

1. **`web` never talks to `api`.** The web container only *serves files*. The React code runs **in the user's browser**, and it is the browser that calls the API, through Caddy, at the same address. (That is why the browser is the thing with `NEXT_PUBLIC_API_URL`, and why there are no server-to-server arrows between web and api.)
2. **Everything behind Caddy is on a private Docker network** and reachable only by service name (`api`, `mcp`, `postgres`, `web`). Nobody outside can reach them because **no ports are published** except Caddy's.

## 1b.2 Why four servers and not one

Each separation exists for a stated reason (Chapter 30: justify a split by a boundary, not fashion):

| Separation | The boundary |
|---|---|
| **postgres separate from api** | *state vs logic*: the API containers can be destroyed and rebuilt freely; the data survives in a volume. Databases also need different operational care (backups, upgrades, disk) |
| **mcp separate from api** | **privilege and attack surface**: the component that can spend search credits and fetch URLs holds only a *public* key and a search key, has *no public address*, and enforces its own limits. If the API were compromised the attacker still has to pass signed-token, single-use, host and rate checks to use the tools, and the tool server cannot mint tokens |
| **web separate from api** | *different runtimes and release cadence*: static UI files (Node) vs Python logic; each scales and deploys independently |
| **caddy in front** | *one door*: one place for HTTPS, routing, and the allow-list of reachable paths; one thing to firewall |

## 1b.3 The connections, one by one

For each arrow: **who initiates → protocol and address → how it authenticates → configured by which variable, set where.**

### Connection 1: Browser → Caddy

* HTTPS on **443** (HTTP on 80 redirects to HTTPS when a real domain is configured; plain HTTP on `:80` for the laptop test).
* Authentication: none at this layer (TLS proves the *server's* identity to the browser). User identity is handled by the API (Connection 3).
* Configured by: `SITE_ADDRESS` (`:80` for local, a hostname such as `203-0-113-7.sslip.io` for a server), `HTTP_PORT` / `HTTPS_PORT` (host ports; `8080` on a laptop). Set in `.env.production`, read by `docker-compose.prod.yml` (`ports: "${HTTP_PORT:-80}:80"`) and passed into the Caddy container as the environment variable `SITE_ADDRESS`.

### Connection 2: Caddy → web, and Caddy → api

* Caddy opens plain HTTP connections to **`web:3000`** and **`api:8000`** over the private Docker network. The names `web` and `api` are resolved by **Docker's built-in DNS** (they are the compose service names).
* Routing rule in `infra/caddy/Caddyfile`: paths `/auth/*`, `/conversations`, `/conversations/*`, `/products/*`, `/admin/*`, `/health` go to the API; **everything else** goes to the web app. `/metrics` is deliberately not in the list, so it is unreachable from outside.
* Configured by: the Caddyfile placeholders `{$API_UPSTREAM:api:8000}` and `{$WEB_UPSTREAM:web:3000}`: environment variables with defaults, so the same file works in Compose (service names) and on platforms that give you addresses (set the variable). Streaming is kept alive with `flush_interval -1`.
* Authentication: none (the network is private; only Caddy can reach these containers).

### Connection 3: Browser → API (through Caddy), with login tokens

* The React app in the browser calls `fetch('/auth/login')`, `fetch('/conversations/...')` etc. on the **same origin**. Caddy forwards those paths to `api:8000`.
* Authentication: a **15-minute access token** (RS256 JWT) in the `Authorization: Bearer` header, and a **refresh token in an HttpOnly cookie** (Chapter 20).
* Why `NEXT_PUBLIC_API_URL` is empty in production: the empty string means "same address as this page", so there is no CORS and the cookie is same-site. It is a **build-time** value baked into the JavaScript (set as a Docker build `ARG` in `apps/web/Dockerfile`), because the browser has no environment variables at runtime.
* In development without Caddy the UI runs at `localhost:3000` and the API at `localhost:8000` (different origins), so `NEXT_PUBLIC_API_URL=http://localhost:8000` and the API's `WEB_ORIGIN=http://localhost:3000` enable CORS.

### Connection 4: API → Postgres

* TCP to **`postgres:5432`**, using `psycopg` (PostgreSQL protocol), authenticated with the **database user and password**.
* One variable carries everything: **`DATABASE_URL=postgresql://stylist:<password>@postgres:5432/stylist`**. In `docker-compose.prod.yml` it is *assembled* from `POSTGRES_PASSWORD`: `postgresql://stylist:${POSTGRES_PASSWORD}@postgres:5432/stylist`, so the password lives in exactly one place and the Postgres container and the API container are guaranteed to agree.
* The API opens **two connection pools** to it (one transactional, one autocommit for LangGraph's checkpointer) (Chapter 17), runs **migrations** at startup (`migrate()`), and creates the checkpoint tables (`saver.setup()`).
* Same variable, **different value per environment**: on the host (`uv run uvicorn`) it is `postgresql://...@localhost:5432/...` (the dev compose publishes 5432 to your laptop); inside Docker it is `@postgres:5432` (the service name). This is the textbook reason configuration lives in environment variables: *the code is identical; only the address changes.*

### Connection 5: API → MCP tool server (the security-critical one)

* HTTP to **`http://mcp:8001/mcp`** (MCP "Streamable HTTP", JSON-RPC) over the private network. Configured by **`MCP_URL`** (compose: `http://mcp:8001/mcp`; host-run default `http://127.0.0.1:8001/mcp`).
* **Every single HTTP request** carries a *brand-new* JWT signed (RS256) with **`MCP_JWT_PRIVATE_KEY`** (held **only by the API**): claims `iss=stylist-api`, `aud=stylist-mcp`, `sub=<end user id>`, `exp = now+30 s`, unique `jti`.
* The MCP server verifies with **`MCP_JWT_PUBLIC_KEY`** (held **only by the MCP server**): checks signature, issuer, audience, expiry with 10 s leeway, a 60 s maximum lifetime, and that the `jti` has **never been used before**.
* Extra guards that make the connection safe even on a shared network: **`MCP_ALLOWED_HOSTS=mcp`** (the server only answers requests whose `Host` header is `mcp`, so a browser or an attacker using another hostname gets 421), `MCP_HOST=0.0.0.0` (listen on all container interfaces *because* no port is published), refusal to start with a non-loopback bind unless `MCP_ALLOWED_HOSTS` is set, per-user rate limit and daily credit caps (`MCP_DAILY_CREDITS_PER_USER`, `MCP_DAILY_CREDITS_GLOBAL`).
* **Why asymmetric keys:** the tool server can *check* that a request came from the API but could never *create* one. Two key pairs exist (`MCP_JWT_*` for this connection, `AUTH_JWT_*` for user logins) so a user's login token is useless here and vice versa.
* The user's identity (`sub`) travels with every call so limits and audit are **per user** even though only the API connects.

### Connection 6: API → the chat model (internet)

* HTTPS to **OpenRouter** (`OPENROUTER_BASE_URL`, default `https://openrouter.ai/api/v1`), OpenAI-compatible protocol, authenticated with **`OPENROUTER_API_KEY`** (a bearer key). Model chosen by **`STYLIST_MODEL`** (`openrouter/apodex/apodex-1.1-mini:free`).
* Only the API holds this key. The model is never given tools and never talks to the tool server.
* Outbound to the internet is allowed from the API container (Docker's default bridge gives it NAT); `FORCE_IPV4` avoids IPv6 stalls.

### Connection 7: MCP → SerpAPI and retailer pages (internet)

* HTTPS from the tool server to **SerpAPI** (`SERPAPI_API_KEY` in the query string; logging of `httpx` is lowered so URLs with keys are never logged) and, for `check_link`, to allow-listed retailer domains using the SSRF-hardened fetcher (resolve once, connect to the checked IP).
* Only the MCP server holds `SERPAPI_API_KEY`. The API has no way to search the web directly.

### Connection 8: Prometheus → API and MCP (`/metrics`), development only

* Prometheus scrapes `api:8000/metrics` and `mcp:8001/metrics` every 10 s with a **bearer token**: `METRICS_TOKEN` in the two services (empty = endpoint off) and the same value mounted into Prometheus as a **Docker secret file** `/run/secrets/metrics_token`. The prod layout does not include Prometheus and Caddy does not route `/metrics`.

### Connection 9: Mastra evals app → API (development)

* The TypeScript app on your laptop calls the API like a real user: `STYLIST_API_URL` (default `http://localhost:8000`), registering/logging in as `eval-bot-N@example.com` accounts. It holds **no** model or search keys (it loads only an allow-list of variables from `.env`).

### Summary table

| From → To | Protocol & address | Credential | Variable(s) |
|---|---|---|---|
| Browser → caddy | HTTPS :443 (or HTTP :80 locally) | TLS cert (server identity) | `SITE_ADDRESS`, `HTTP_PORT`, `HTTPS_PORT` |
| caddy → web | HTTP `web:3000` | none (private net) | `WEB_UPSTREAM` |
| caddy → api | HTTP `api:8000` | none (private net) | `API_UPSTREAM` |
| browser → api (via caddy) | HTTPS, same origin | access JWT + refresh cookie | `NEXT_PUBLIC_API_URL` (build), `WEB_ORIGIN`, `COOKIE_SECURE`, `AUTH_JWT_*` |
| api → postgres | PostgreSQL `postgres:5432` | DB user + password | `DATABASE_URL` (built from `POSTGRES_PASSWORD`) |
| api → mcp | HTTP `mcp:8001/mcp` | fresh RS256 JWT per request | `MCP_URL`, `MCP_JWT_PRIVATE_KEY` (api), `MCP_JWT_PUBLIC_KEY` (mcp), `MCP_ALLOWED_HOSTS` |
| api → OpenRouter | HTTPS | bearer API key | `OPENROUTER_API_KEY`, `STYLIST_MODEL` |
| mcp → SerpAPI / stores | HTTPS | API key (SerpAPI) | `SERPAPI_API_KEY`, allow-lists in code |
| prometheus → api/mcp | HTTP `/metrics` | bearer token | `METRICS_TOKEN` + secret file |
| mastra → api | HTTP | user login | `STYLIST_API_URL`, `EVAL_*` |

## 1b.4 The environment files: what, where, and why there

An **environment file** is a text file of `NAME=value` lines that is turned into **environment variables** for a program. This project has several, each at a specific location for a specific reason.

### The files

| File | Location | Committed to git? | Who reads it | Purpose |
|---|---|---|---|---|
| **`.env.example`** | repo root | **yes** | humans, and `test_repo_hygiene.py` | the **template**: every setting's name, safe defaults, and comments. **Contains no secrets** (a test fails if it does) |
| **`.env`** | repo root | **no** (git-ignored) | (a) **docker compose** (dev) automatically, for `${VAR}` substitution; (b) the API's and MCP's `Settings` classes when run on the host; (c) Mastra's allow-listed loader; (d) the helper scripts that write keys into it | your **real local development values** |
| **`.env.production`** | repo root | **no** (git-ignored) | **docker compose** via `--env-file .env.production` (prod stack) | the **hosted/laptop-prod values**, created by scripts; every secret for the prod stack |
| **`infra/observability/.secrets/metrics_token`** | under `infra/observability/` | **no** (git-ignored) | **Prometheus** (mounted as a Docker secret file) | the bearer token Prometheus uses to read `/metrics` |
| **Dockerfile `ENV` lines** | inside each Dockerfile | yes (they are code) | the container at runtime | **non-secret, secure defaults** baked into images (`ENVIRONMENT=prod`, `COOKIE_SECURE=true`, `PYTHONUNBUFFERED=1`) |
| **Compose `environment:` blocks** | inside the compose files | yes (placeholders only) | the container at runtime | the **explicit list of variables each service receives**, filled by interpolation from the env file |

Notice what is *not* in the list: **no `.env` file exists inside any container.** `.dockerignore` excludes `.env`, `.env.*` and `*.pem` from every build, so secrets cannot enter an image layer. Containers get their configuration purely as **runtime environment variables injected by Compose**.

### Why `.env` is at the repo root (and not inside each service)

1. **One place to set shared values** for several programs (`API`, `MCP`, `Mastra`, `docker compose`, scripts) instead of keeping copies in sync.
2. **Compose reads `.env` from the project directory automatically.** The compose files sit at the repo root, so a root `.env` is picked up with no flags.
3. **The Python services find it by walking upward.** Both `services/api/src/api/config.py` and `services/mcp/src/mcp_server/config.py` call `_find_env_file()`, which checks each parent directory of the module for a `.env` and uses the first found. Run from `services/api`, the walk reaches the repo root. This is a **developer convenience**: it lets `uv run uvicorn ...` work from any subfolder.
4. **The scripts write there**: `scripts/generate_jwt_keys.py` writes keys into `<repo>/.env` (or the file named by `--out`), and `init_observability.py` adds `METRICS_TOKEN` there.
5. **It is git-ignored**, so secrets never travel with the code. The committed `.env.example` shows the shape.

Honest trade-off: in local development both the API and the MCP server read the **same root `.env`**, which contains **both the private and public keys**. That temporarily violates least privilege (the tool server process *could* read the private key). It is acceptable on a laptop, and it is exactly why **Docker Compose does not do this**: in containers each service receives *only* the variables listed in its `environment:` block (below), so the MCP container never sees a private key.

### Why `.env.production` is a *separate* file, and used with `--env-file`

* It must **never mix with dev values** (dev uses `stylist_dev_password`, `COOKIE_SECURE=false`, `ENVIRONMENT=dev`). A separate file makes the choice explicit: `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
* **`--env-file` replaces the default `.env`** for that command, so dev keys can never leak into the prod stack by accident.
* It is **created by scripts, in a fixed order**, so nothing is hand-typed wrong:
  1. `python scripts/generate_jwt_keys.py --out .env.production` creates the **two RSA key pairs** (`MCP_JWT_*`, `AUTH_JWT_*`) as single-line values (with literal `\n`) and prints only fingerprints.
  2. `python scripts/init_production_env.py [--server <name>]` **adds only what is missing**: a random `POSTGRES_PASSWORD`; address settings (`SITE_ADDRESS`, `PUBLIC_URL`; for a laptop test also `HTTP_PORT=8080` and `COOKIE_SECURE=false`); and **copies** `STYLIST_MODEL`, `OPENROUTER_API_KEY`, `SERPAPI_API_KEY`, `ADMIN_EMAILS` from `.env` as a local-testing convenience. It never prints secrets, and tells you which keys are still empty.
  3. You fill any remaining values by hand (on a real server: the *new*, rotated model and search keys).
* On a server: `chmod 600 .env.production`, keep it out of git, and generate the keys **on the server** so private keys never travel.

### How a value gets from a file into a running program

```
.env.production  ──(compose reads with --env-file)──►  interpolation of ${VAR} in docker-compose.prod.yml
                                                              │
                          each service's `environment:` list picks ONLY the variables it needs
                                                              ▼
                                         container's environment (real OS environment variables)
                                                              ▼
                       pydantic-settings Settings class reads them (field `mcp_jwt_private_key` ← MCP_JWT_PRIVATE_KEY)
                                                              ▼
                                              your code uses `cfg.mcp_jwt_private_key`
```

Precedence for a Python service: **real environment variables > `.env` file > defaults in the `Settings` class.** In a container there is no `.env`, so the environment variables win by default; if a variable is missing the Python default (often a safe/dev default or empty) is used. `${VAR:?message}` in the prod compose makes the stack **refuse to start** with a helpful message if a required variable is missing (`POSTGRES_PASSWORD`, `MCP_JWT_PUBLIC_KEY`).

### The variable matrix: which server receives which variables, and why

Read this as the **least-privilege wiring table** (production compose):

| Variable | postgres | mcp | api | web | caddy | Why this placement |
|---|:--:|:--:|:--:|:--:|:--:|---|
| `POSTGRES_PASSWORD` / `DATABASE_URL` | ✔ (password) | – | ✔ (URL) | – | – | only the DB and its one client need it |
| `MCP_JWT_PRIVATE_KEY` | – | – | ✔ | – | – | **signing power stays with the API** |
| `MCP_JWT_PUBLIC_KEY` | – | ✔ | – | – | – | **verification only** |
| `AUTH_JWT_PRIVATE_KEY`, `AUTH_JWT_PUBLIC_KEY` | – | – | ✔ | – | – | user login tokens are signed and verified by the API only |
| `OPENROUTER_API_KEY`, `STYLIST_MODEL` | – | – | ✔ | – | – | only the API calls the model |
| `SERPAPI_API_KEY` | – | ✔ | – | – | – | only the tool server searches |
| `MCP_URL` | – | – | ✔ | – | – | the API needs to know where the tool server is |
| `MCP_HOST`, `MCP_ALLOWED_HOSTS` | – | ✔ | – | – | – | the tool server's own binding and host guard |
| `MCP_DAILY_CREDITS_PER_USER`, `MCP_DAILY_CREDITS_GLOBAL` | – | ✔ | – | – | – | the tool server enforces credit caps |
| `WEB_ORIGIN` (from `PUBLIC_URL`) | – | – | ✔ | – | – | CORS origin (and cookie context) |
| `COOKIE_SECURE`, `ENVIRONMENT`, `BACKEND_MODE`, `ADMIN_EMAILS` | – | – | ✔ | – | – | API behaviour switches |
| `FORWARDED_ALLOW_IPS` | – | – | ✔ | – | – | trust Caddy's `X-Forwarded-For` |
| `METRICS_TOKEN` | – | ✔ (dev) | ✔ (dev) | – | – | `/metrics` auth (empty = off) |
| `NEXT_PUBLIC_API_URL` | – | – | – | **build-time only** | – | baked into the browser JavaScript; public, empty = same origin |
| `SITE_ADDRESS`, `HTTP_PORT`, `HTTPS_PORT` | – | – | – | – | ✔ | the door's address and ports |
| `API_UPSTREAM`, `WEB_UPSTREAM` | – | – | – | – | ✔ (optional) | where Caddy forwards |

Rules this encodes: **a secret goes only to the server that uses it; no variable is shared "just in case"; the web server receives no secrets at all** (it serves public files); and values that *are* shared (the database password) are defined once and referenced.

### Build-time versus runtime variables

* **Runtime** (almost all): injected when the container starts; changing them needs only `up -d` (container recreated).
* **Build-time**: `NEXT_PUBLIC_API_URL` is consumed during `next build` and **inlined into the JavaScript**. Changing it requires **rebuilding the web image**. It must therefore never be a secret.
* **Image defaults** (`ENV` in Dockerfiles): `ENVIRONMENT=prod`, `COOKIE_SECURE=true` ("safe unless deliberately relaxed"); compose overrides them for dev.

## 1b.5 How the servers start: order, health and readiness

Production compose startup (the dependencies are expressed in YAML, not in your head):

```
postgres ──healthy (pg_isready)──┐
mcp ──────healthy (/health)──────┼──► api starts ──► (migrations run, pools open, checkpoint tables created)
                                 │
web ────────────────────────────────────────────┐
api ─────────────────────────────────────────────┴──► caddy starts (depends_on: [api, web])
```

* `api` has `depends_on: { postgres: {condition: service_healthy}, mcp: {condition: service_healthy} }`. Health comes from `pg_isready` and the images' `HEALTHCHECK` (`GET /health`).
* `caddy` waits for `api` and `web` to *start* (they have no health condition; `web` has no healthcheck defined). Caddy retries upstreams on its own.
* Ordering only covers startup. If Postgres restarts later, the API's pool reconnects (psycopg pool) but requests may fail meanwhile; hence retries and `restart: unless-stopped`.

## 1b.6 Building it from scratch, in order, with a check after each step

This is the order that minimises debugging: **start at the bottom of the dependency chain and prove each connection before adding the next.**

### Step 1: the database

```bash
docker compose up -d postgres                       # dev compose: publishes 5432 for your tools
docker compose exec postgres pg_isready -U stylist  # expect: accepting connections
```
Prove: you can connect with the URL the API will use: `psql postgresql://stylist:stylist_dev_password@localhost:5432/stylist -c "select 1"`.

### Step 2: create the keys and the env file

```bash
cp .env.example .env
uv run --project services/mcp python scripts/generate_jwt_keys.py        # writes both RSA pairs into .env
```
Prove: `.env` now has non-empty `MCP_JWT_*` and `AUTH_JWT_*` names (print **names only**; never `cat` the file). Fill `OPENROUTER_API_KEY` and `SERPAPI_API_KEY` yourself. Confirm git ignores it: `git check-ignore -v .env`.

### Step 3: the MCP tool server

```bash
(cd services/mcp && uv sync && uv run python -m mcp_server.server)       # host-run for development: 127.0.0.1:8001
```
Prove: `curl http://127.0.0.1:8001/health` → `{"status":"ok"}`; calling `/mcp` **without a token** is refused (401); a client with a signed token can `list_tools`. This proves the public key loaded and auth works.

### Step 4: the API

```bash
(cd services/api && uv sync && uv run uvicorn api.main:app --port 8000)
```
Prove: `curl localhost:8000/health` → ok; startup log shows migrations applied (connection to Postgres works); register a user with curl and receive an access token; (`BACKEND_MODE=demo` lets you test the whole flow without model or search keys). Now a real chat turn proves the API→MCP connection and the model key.

### Step 5: the web app

```bash
npm install && npm run dev -w apps/web          # http://localhost:3000, NEXT_PUBLIC_API_URL=http://localhost:8000
```
Prove: open the page, register, run a conversation. In dev the browser (3000) talks to the API (8000) directly: different origins, so CORS is active (`WEB_ORIGIN`).

### Step 6: put it all in containers, then add the door

```bash
docker compose up -d                            # dev compose: postgres + mcp + api (mcp has no ports)
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build   # prod layout: + web + caddy; only Caddy publishes ports
```
Prove each connection **from inside the network**:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec api python -c "import urllib.request;print(urllib.request.urlopen('http://mcp:8001/health').read())"
docker compose -f docker-compose.prod.yml --env-file .env.production exec caddy wget -qO- http://api:8000/health
curl -i http://localhost:8080/health            # through Caddy
curl -i http://localhost:8080/metrics           # must NOT reach the API (falls through to the web app's 404)
# from the HOST these must FAIL (nothing published): curl localhost:8001, curl localhost:5432, curl localhost:8000
```

### Step 7: verify the security-relevant wiring

* MCP container environment contains **no** private key (check *names*: `docker compose exec mcp sh -c 'env | cut -d= -f1 | sort'`).
* `docker compose ps` shows only Caddy with published ports.
* A direct request to the MCP server with a foreign `Host` header returns 421.
* Register through the UI; the refresh cookie is `HttpOnly; SameSite=Strict; Path=/auth` (and `Secure` over HTTPS).

## 1b.7 Adding another server (the recipe)

Suppose you add **Redis** (Chapter 32) or a **worker**. Checklist:

1. **Decide the boundary**: why a separate server? (state, privilege, scaling, language).
2. **Add the service to compose**: image or `build:`, **no `ports:`** unless it must be public, `restart`, healthcheck, hardening (`read_only`, `cap_drop: [ALL]`, `no-new-privileges`, `mem_limit`, `pids_limit`), non-root user.
3. **Put it on the same private network** (default) and refer to it **by service name** (`redis:6379`).
4. **Give it its own credentials**; add the variable to `.env.example` (name only, no secret), to the env-file generator script, and to the `environment:` of **only the services that call it** (for example `REDIS_URL` for `api` and `mcp`).
5. **Add `depends_on` with a health condition** for services that need it at startup.
6. **Authenticate the connection** (password/TLS/token) even on a private network (defence in depth).
7. **Add its address variable with a different value per environment** (`localhost` on the host, service name in Docker).
8. **Observability**: `/metrics` or exporter, logs to stdout, a dashboard row.
9. **Tests and docs**: a connection test (fake in unit tests; real in integration), update the diagram and the matrix in this chapter.
10. **Security review**: does it widen the attack surface? Who can reach it? Which secrets did it add?

## 1b.8 Troubleshooting the wiring

| Symptom | Likely cause | Where to look |
|---|---|---|
| API starts, then "connection refused" to Postgres | `DATABASE_URL` host is `localhost` inside a container (should be `postgres`) | the `environment:` block; `docker compose logs api` |
| API → MCP returns 421 | `Host` header not in `MCP_ALLOWED_HOSTS` (you used an IP or other name) | `MCP_URL` must use the name `mcp`; allowed hosts must list it |
| API → MCP returns 401 | keys not a matching pair; clock skew > 10 s; token reused; `MCP_JWT_PUBLIC_KEY` missing | MCP logs show the *reason* (`invalid_token`, `clock_or_expiry`, `replay`); regenerate the pair together |
| MCP container exits immediately | public key missing/invalid (**by design: fail closed**), or non-loopback bind without allowed hosts | `docker compose logs mcp` |
| Stack refuses to start: "run scripts/init_production_env.py" | a required variable is empty (`:?` guard) | create/fill `.env.production` |
| Login works but you are logged out on reload | `COOKIE_SECURE=true` over plain HTTP, or different origin | match `COOKIE_SECURE` to the scheme; same origin via Caddy |
| UI calls the wrong API address | `NEXT_PUBLIC_API_URL` was baked at build time with the wrong value | rebuild the web image with the right build arg |
| Prometheus target "down" | wrong token/secret file or `METRICS_TOKEN` empty in the service | `init_observability.py`; both sides must share the value |
| Buy link says "Unknown or expired product_id" | different MCP instance than the search (after scaling) or >6 h elapsed | Chapter 32 (shared cache) |
| "works on host, fails in Docker" | `localhost`/127.0.0.1 inside a container is the container | use service names |

## 1b.9 The Railway layout: the same system as four services

`docs/deploy.md` (section 3) and `apps/web/Dockerfile.railway` describe deploying this system on **Railway** as **four services: Postgres, mcp, api, web**. This is the layout the "four servers" refers to when you deploy to a platform instead of a VM. The architecture is identical; **what changes is who provides the network, the door, and the environment**.

> **Source of truth.** The repo-specific facts below come from `Dockerfile.railway`, `docs/deploy.md`, `infra/caddy/Caddyfile` and `services/mcp/tests/test_key_format.py`. Facts about Railway itself (private hostnames, variable references, networking) are marked *(verify in Railway's docs)* because platforms change.

### Why four services and not five

On the VM layout the door (Caddy) is its own container (five containers). The deploy guide explains why that changes on Railway: *"Railway's smaller plans cap the number of services per project, and its private network does not cross projects, so the door (Caddy) and the web app share one container."* So Caddy moves **inside the web service**, and the project has exactly four services:

```
                           INTERNET (HTTPS, terminated by Railway's edge for the web service's public domain)
                                      │
                                      ▼  public port 8080
        ┌──────────────────────────────────────────────────────────────────────────┐
        │  web service  (apps/web/Dockerfile.railway)  ── ONE container, TWO processes │
        │     Caddy  listening on :8080   (SITE_ADDRESS=:8080, plain HTTP inside)     │
        │       ├─ /auth /conversations /products /admin /health ──► API_UPSTREAM      │──► api service  (private address :8000)
        │       └─ everything else ──► WEB_UPSTREAM=127.0.0.1:3000                    │
        │     Next.js listening on 127.0.0.1:3000  (not reachable from outside)       │
        └──────────────────────────────────────────────────────────────────────────┘
                 api service ──► Postgres service   (private network, DATABASE_URL)
                 api service ──► mcp service        (private network, MCP_URL, signed tokens)
                 mcp service ──► SerpAPI / retailers (internet)
                 api service ──► OpenRouter          (internet)
        ONLY the web service has a public address. api, mcp and Postgres have none.
```

### How the combined web container works (`Dockerfile.railway`)

* **Same build stage as the normal web image** (Next.js build with the build-arg `NEXT_PUBLIC_API_URL=""`, meaning same origin).
* **Final stage adds Caddy**: `COPY --from=caddy:2 /usr/bin/caddy /usr/bin/caddy` (copies just the binary from the official image) and `COPY infra/caddy/Caddyfile /etc/caddy/Caddyfile`: the **same Caddyfile** as the VM layout. That works because the Caddyfile reads its addresses from **environment placeholders** (`{$SITE_ADDRESS::80}`, `{$API_UPSTREAM:api:8000}`, `{$WEB_UPSTREAM:web:3000}`): the file never changes, only the variables do.
* **Baked defaults** (in `ENV`): `SITE_ADDRESS=:8080` (plain HTTP on 8080; Railway terminates TLS at its edge), `WEB_UPSTREAM=127.0.0.1:3000` (the Next.js process in the *same container*). **`API_UPSTREAM` is not baked**: it must be set per deployment to the api service's private address (`<api private address>:8000`).
* `XDG_DATA_HOME=/tmp XDG_CONFIG_HOME=/tmp`: Caddy writes small state files; this points them at a place the non-root `node` user may write.
* `USER node`, `EXPOSE 8080`.
* **Two processes in one container**:

```bash
CMD ["bash", "-c", "node .../next start apps/web -H 127.0.0.1 -p 3000 & caddy run --config /etc/caddy/Caddyfile --adapter caddyfile & wait -n; exit 1"]
```

  Both are started in the background; `wait -n` returns as soon as **either** exits, then `exit 1` ends the container so the platform restarts it ("if either one stops, the container exits so the host restarts it"). Next.js is bound to **`127.0.0.1`** so the *only* way in is through Caddy. This deliberately **breaks the "one process per container" rule** (Chapter 25) to fit a service-count limit; the trade-off is that the two processes share one lifecycle and one set of resources, and PID 1 is `bash`, so signal handling is less clean than with exec-form `CMD`.

### The environment on Railway: no env file at all

On a VM you create `.env.production` and pass it with `--env-file`. **Railway replaces that file with its per-service Variables settings.** Each service has its own variables; at deploy time the platform injects them as **real environment variables** into that service's container, which is exactly what the Python `Settings` classes already read (the precedence rule: real environment variables beat `.env`; in a container there is no `.env`). So the **same variable names** from the matrix in 1b.4 apply; they are just entered in the platform UI **per service**, not in a file. **Treat the platform's variable store as your secret manager** (the values live with a third party; use its secret/sealed-variable features if available *(verify)*).

| Railway service | Variables to set | Why on this service |
|---|---|---|
| **Postgres** | managed by Railway (it provides the connection details) | the database; no code of yours runs here |
| **mcp** | `MCP_JWT_PUBLIC_KEY`, `SERPAPI_API_KEY`, `MCP_HOST=0.0.0.0`, `MCP_ALLOWED_HOSTS=<the mcp service's private hostname>`, `MCP_DAILY_CREDITS_PER_USER`, `MCP_DAILY_CREDITS_GLOBAL`, optionally `METRICS_TOKEN` | public key and search key only; **no private key**; the host allow-list must contain the exact name the API uses to reach it |
| **api** | `DATABASE_URL` (pointing at the Postgres service's private address), `MCP_URL=http://<mcp private address>:8001/mcp`, `MCP_JWT_PRIVATE_KEY`, `AUTH_JWT_PRIVATE_KEY`, `AUTH_JWT_PUBLIC_KEY`, `STYLIST_MODEL`, `OPENROUTER_API_KEY`, `WEB_ORIGIN=<public https URL of the web service>`, `ADMIN_EMAILS`; image defaults already give `ENVIRONMENT=prod` and `COOKIE_SECURE=true`; consider `FORWARDED_ALLOW_IPS` so the API trusts the proxy's forwarded client address | signing keys and model key live only here |
| **web** | `RAILWAY_DOCKERFILE_PATH=apps/web/Dockerfile.railway` (tells Railway which Dockerfile to build), root directory left empty (the build context must be the **repo root**), `PORT=8080` (the port the public domain should target), `API_UPSTREAM=<api private address>:8000` | public door settings; **no secrets** |

Key relationships you must get right (most deployment failures are here):

1. **`MCP_URL` (on api) and `MCP_ALLOWED_HOSTS` (on mcp) must name the same host.** The MCP server answers only requests whose `Host` header is in its allow-list; the API sends `Host: <hostname in MCP_URL>`. On compose that name is `mcp`; on Railway it is the mcp service's **private hostname** *(verify the exact form, commonly `<service>.railway.internal`)*. A mismatch produces **421** errors.
2. **`API_UPSTREAM` (on web) points at the api service's private address and port 8000**; it is *not* a public URL.
3. **`DATABASE_URL` (on api)** must use the Postgres service's **private** connection string, not a public proxy URL (keep the database off the internet). Railway can reference another service's variables from yours *(verify the reference syntax in Railway's docs)* so the password is defined once.
4. **`MCP_JWT_PRIVATE_KEY` (api) and `MCP_JWT_PUBLIC_KEY` (mcp) must be a matching pair**, and the **auth pair** only on the api; regenerate keys together, never one half.
5. **`WEB_ORIGIN` (api)** should equal the web service's public URL, so CORS/cookie origin checks agree (same-origin through Caddy means CORS is not exercised, but the origin setting still must be right).
6. **`NEXT_PUBLIC_API_URL`** stays empty (same origin) and is a **build-time** value baked into the JS; if you ever set it, rebuild the web service.
7. **Only the web service gets a public domain** (generate it targeting port 8080). Do **not** generate public domains for api, mcp or Postgres, and do not enable a public database TCP proxy; if a separate `caddy` service exists from earlier attempts, delete it (as the guide says).

### Pasting keys into a variables screen: why the code now strips quotes

The two RSA PEM keys are multi-line, but a variable value must be one line, so the key scripts write them with literal `\n` markers and the settings convert them back. Platform variable screens add another trap: **values pasted with surrounding quote marks may be stored with the quotes included**. The settings code was therefore hardened: the `*_pem` properties now do `value.strip().strip("\"'").replace("\\n", "\n").strip()`, and `services/mcp/tests/test_key_format.py` proves the public key loads in **four spellings** (`{}`, `"{}"`, `'{}'`, `' "{}" '`). Because the MCP server **refuses to start without a valid public key** (fail closed), an unreadable key shows up as a crash loop at start-up; the test exists so that failure mode is fixed at the source. Workflow: generate the pairs locally with `generate_jwt_keys.py --out .env.production`, copy each value **by name** into the right service's variables (never commit that file), then delete the local copy if you do not need it.

### What changes compared with the VM layout

| Aspect | VM + Compose | Railway (four services) |
|---|---|---|
| Containers/services | postgres, mcp, api, web, caddy | Postgres, mcp, api, web (**Caddy inside web**) |
| Door | Caddy container publishing 80/443; Let's Encrypt via ACME | Railway edge terminates TLS; Caddy listens on plain `:8080` |
| Private network | one Docker network; names `api`, `mcp`, `postgres`, `web` | Railway's private network; addresses are the platform's private hostnames *(verify)*; **does not cross projects** |
| Config | `.env.production` + `--env-file` + compose `environment:` | per-service Variables in the platform UI |
| Startup ordering | `depends_on` with health conditions | none by default: services start independently, so every client must retry (the API reconnects to Postgres; the MCP client retries once) |
| Hardening flags (`read_only`, `cap_drop`...) | set in compose | **not under your control** on most PaaS; rely on the image (non-root users, no secrets) and the platform's isolation |
| Persistence | named volumes (`pgdata`) | the platform's managed Postgres volume/backups *(verify plan features)* |
| Scaling | manual | per-service replicas possible, but the in-process state limits apply (Chapter 32) |

### Verification checklist on Railway

* Public URL `/health` returns `{"status":"ok"}` (web → Caddy → api).
* Registering works and the refresh cookie is `HttpOnly; Secure; SameSite=Strict; Path=/auth` (HTTPS at the edge, `COOKIE_SECURE=true`).
* A demo-mode or real chat turn streams events progressively (if everything arrives at once, check buffering at the platform edge; Caddy already flushes).
* The api, mcp and Postgres have **no public domain**; attempting to reach them from the internet fails.
* api logs show migrations applied and a successful call to `mcp`; mcp logs show no `421`/`401` refusals.
* `/metrics` on the public URL does not expose the API's metrics (falls through to the web app's 404).

### Troubleshooting on Railway

| Symptom | Likely cause |
|---|---|
| web returns 502 for API paths | `API_UPSTREAM` wrong, api not running, or api listening on a different port |
| api fails at start with database errors | `DATABASE_URL` points at a public/wrong address or the DB is not ready yet (retry/redeploy) |
| mcp crash-loops at start | `MCP_JWT_PUBLIC_KEY` empty/garbled (quotes, truncated PEM) *(fail closed by design)* |
| api→mcp returns 421 | `MCP_ALLOWED_HOSTS` does not contain the hostname used in `MCP_URL` |
| api→mcp returns 401 | key pair mismatch, clock skew, or replayed token |
| api cannot reach mcp at all | wrong private hostname/port; or the platform's private network address family differs from what the server binds (older Railway environments used IPv6-only private networking, so a server bound only to `0.0.0.0` may be unreachable; check Railway's current docs and bind to `::` if required) *(verify)* |
| login works, then logged out on reload | cookie/origin mismatch: `COOKIE_SECURE`, wrong `WEB_ORIGIN`, or the page is not served from the same public domain |
| UI calls the wrong API address | stale build with the wrong `NEXT_PUBLIC_API_URL`; rebuild |
| build fails to find files | root directory not left empty (build context must be the repo root) or `RAILWAY_DOCKERFILE_PATH` unset |

## Common mistakes

* Putting secrets in the compose file, Dockerfile, image, or git.
* Sharing one big env file with every service "for convenience" (violates least privilege).
* Using `localhost` between containers.
* Publishing `ports:` for services that should be private.
* Forgetting that `NEXT_PUBLIC_*` is build-time and public.
* Editing `.env` and expecting running containers to change (they need recreation).
* Regenerating only one half of a key pair.
* Mixing dev and prod env files.

## Summary

* Five containers in production: **postgres** (data), **mcp** (private tools), **api** (brain and rules), **web** (UI files), **caddy** (the only public door). Dev adds optional observability containers; Mastra is a client on your laptop.
* Connections: browser → caddy → {web, api}; api → postgres (`DATABASE_URL`), api → mcp (signed single-use token per request, `MCP_URL`), api → OpenRouter, mcp → SerpAPI. The browser, not the web server, calls the API.
* Env files: `.env.example` (committed template), `.env` (local, root, git-ignored, read by compose, the Python services and scripts), `.env.production` (prod, created by two scripts, passed with `--env-file`), a secret file for Prometheus, Dockerfile `ENV` for safe defaults; **no env files inside containers**.
* Each service receives only the variables it needs (least privilege); build-time `NEXT_PUBLIC_API_URL` is public; same variable names, different values per environment.
* Build bottom-up and prove each connection before adding the next.
* **On Railway** the same system runs as four services (Postgres, mcp, api, web with Caddy inside it): there is no env file, each service has its own variables in the platform UI, private addresses replace Docker service names, and the key relationships (`MCP_URL` ↔ `MCP_ALLOWED_HOSTS`, `API_UPSTREAM`, matching key pairs, a public domain on `web` only) decide whether it works.

## Key terms

*service, private network, service-name DNS, published port, environment variable, env file, interpolation, `--env-file`, build-time vs runtime variable, least-privilege wiring, health-gated startup, upstream, same origin.*

## Interview questions

1. Draw the servers of this system and label every connection with protocol, address and credential.
2. Why does the tool server hold only a public key? Which variable carries each key and to which container?
3. Why is there a separate `.env.production`, and how is it created and used?
4. Why does `DATABASE_URL` use `localhost` in one place and `postgres` in another?
5. Why is `NEXT_PUBLIC_API_URL` empty in production, and when is it read?
6. Which containers can the internet reach? How do you prove the others are unreachable?
7. How would you add Redis to this system safely?

## Exercises

1. Draw the connection diagram from memory, then verify every arrow against the compose files.
2. Print the *names* (never values) of the environment variables inside each running container and compare with the matrix; explain any difference.
3. Break each connection on purpose (wrong `DATABASE_URL` host, mismatched key pair, wrong `MCP_ALLOWED_HOSTS`, empty `METRICS_TOKEN`) and record the exact symptom and log line.
4. Add a `redis` service following the recipe in 1b.7 (no published port, password, healthcheck, variable only to the services that need it).
5. Rebuild the whole stack from an empty clone following 1b.6 and write down every place you needed information that was not in the docs.
