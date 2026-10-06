# Deploying the stylist (laptop first, then one small server)

One layout, two places to run it. Test it on your laptop; the same files run on a server.

```
Browser ──► caddy (the only published ports)
              ├─ /auth /conversations /products /admin /health ─► api ──► postgres
              │                                                    └────► mcp (tool server)
              └─ everything else ───────────────────────────────► web
```

Only **caddy** is reachable from outside. The database, tool server, API and web app publish no ports.
`/metrics` is not routed, so it stays unreachable. The web app and API share one address, so the browser
treats them as one site: the "stay signed in" cookie (SameSite=Strict) works and no domain purchase is needed.

## 1. On your laptop

Needs Docker Desktop running.

```bash
uv run --project services/mcp python scripts/generate_jwt_keys.py --out .env.production   # new signing keys
python scripts/init_production_env.py        # database password, addresses; copies model/search keys from .env
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

Open http://localhost:8080.

**Free test with no model or search calls:** add these two lines to `.env.production` before the `up` command
(demo mode is refused in production, hence `ENVIRONMENT=dev`):

```
ENVIRONMENT=dev
BACKEND_MODE=demo
```

Remove them (and run `up -d` again) for the real model and real search. Real mode uses your model quota
(the free model allows 50 requests a day, about 8 conversations) and Tavily credits.

Handy commands (same `-f ... --env-file ...` prefix):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps           # what is running
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api  # JSON logs
docker compose -f docker-compose.prod.yml --env-file .env.production down         # stop (keeps the data)
docker compose -f docker-compose.prod.yml --env-file .env.production down -v      # stop AND delete the data
```

## 2. On a server

Any small Linux machine with Docker (an Oracle Cloud "Always Free" VM, or a cheap VPS), 2 GB RAM or more.

1. Use your OpenRouter and Tavily keys below (rotate them first if they ever appeared anywhere public).
2. Point a name at the server. A free one works: `<server-ip-with-dashes>.sslip.io` (for 203.0.113.7 that
   is `203-0-113-7.sslip.io`), or your own domain's A record.
3. Open ports 80 and 443 in the provider's firewall. Open nothing else.
4. Copy the project to the server (`git clone` of the repo), then create the keys on the server so they never
   travel: `generate_jwt_keys.py --out .env.production`, then
   `python scripts/init_production_env.py --server <your-name>`.
5. Put `OPENROUTER_API_KEY`, `TAVILY_API_KEY` and your `ADMIN_EMAILS` in `.env.production` by hand.
6. `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
   Caddy fetches the https certificate by itself on first visit.

Do not set `ENVIRONMENT`/`BACKEND_MODE` on a server: the defaults are production and real mode.

## 3. On Railway (four services: Postgres, mcp, api, web)

Railway's smaller plans cap the number of services per project, and its private network does not cross
projects, so the door (Caddy) and the web app share one container: `apps/web/Dockerfile.railway`.

* `web` service: `RAILWAY_DOCKERFILE_PATH=apps/web/Dockerfile.railway`, root directory empty,
  `PORT=8080`, `API_UPSTREAM=<api private address>:8000`. Generate its public domain with port 8080.
* `api`, `mcp`, `Postgres`: as described in the main steps. Only `web` has a public address.
* If a separate `caddy` service exists, delete it.

## Search settings the tool server needs

The product search is a model searching the web through OpenRouter, so the **mcp** service needs `OPENROUTER_API_KEY` (the
same key the API uses). Optional: `SEARCH_PROVIDER` (`openrouter` default, or `tavily` with `TAVILY_API_KEY`), `SEARCH_MODEL`
(default `openai/gpt-6-luna`). On Railway set these on the **mcp** service; on **api** set `STYLIST_MODEL`.

## Long replies (important)

One agent turn streams its answer for 1 to 2 minutes (a model call, then store searches). Two settings keep that alive and
are pinned by tests (`services/api/tests/test_deploy_config.py`):

* **Caddy `request_buffers`** (infra/caddy/Caddyfile). Measured on Caddy 2.11: without it, a long POST response is cut at
  exactly 60 seconds and the shopper never gets the outfits (GET streams were never affected). With it, the stream runs
  to the end. Railway's `web` service runs this same Caddyfile.
* **A keep-alive every 10 seconds** from the API while the agent is working, so no proxy sees a silent connection.

To test a long turn without spending model quota: `DEMO_PLAN_DELAY_S=70` with `BACKEND_MODE=demo` and `ENVIRONMENT=dev`
makes the scripted planner take 70 seconds.

## Limits and honest notes

* `.env.production` holds every secret in one file. It is git-ignored. On a server, keep it readable by you only
  (`chmod 600`).
* There are no usage limits by default (nothing is refused for being too fast or too frequent). The only ceilings
  are your providers' own: the chat model's request limit and your search plan's quota. When a provider refuses,
  everyone sees a friendly "try again later". To bring a limit back, set it in `.env.production`:
  `CHAT_MESSAGES_PER_MIN`, `DAILY_CONVERSATIONS_PER_USER`, `BUY_LINKS_PER_MIN`, `IP_AUTH_CALLS_PER_MIN` (API) and
  `MCP_RATE_LIMIT_PER_MIN`, `MCP_DAILY_CREDITS_PER_USER`, `MCP_DAILY_CREDITS_GLOBAL` (tool server); `0` means no limit.
  The login lockout (5 wrong passwords) is not a usage limit and stays on.
* No backups are configured. The database lives in a Docker volume on that one machine.
* Jaeger/Prometheus/Grafana are not part of this layout (see docs/observability.md for the local stack).
* In demo mode the Buy button opens an empty tab (the mock links go nowhere).
