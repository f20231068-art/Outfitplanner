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
(the free model allows 50 requests a day, about 8 conversations) and SerpAPI credits.

Handy commands (same `-f ... --env-file ...` prefix):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production ps           # what is running
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api  # JSON logs
docker compose -f docker-compose.prod.yml --env-file .env.production down         # stop (keeps the data)
docker compose -f docker-compose.prod.yml --env-file .env.production down -v      # stop AND delete the data
```

## 2. On a server

Any small Linux machine with Docker (an Oracle Cloud "Always Free" VM, or a cheap VPS), 2 GB RAM or more.

1. Rotate your OpenRouter and SerpAPI keys; use the NEW ones below.
2. Point a name at the server. A free one works: `<server-ip-with-dashes>.sslip.io` (for 203.0.113.7 that
   is `203-0-113-7.sslip.io`), or your own domain's A record.
3. Open ports 80 and 443 in the provider's firewall. Open nothing else.
4. Copy the project to the server (`git clone` of the repo), then create the keys on the server so they never
   travel: `generate_jwt_keys.py --out .env.production`, then
   `python scripts/init_production_env.py --server <your-name>`.
5. Put the NEW `OPENROUTER_API_KEY`, `SERPAPI_API_KEY` and your `ADMIN_EMAILS` in `.env.production` by hand.
6. `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`.
   Caddy fetches the https certificate by itself on first visit.

Do not set `ENVIRONMENT`/`BACKEND_MODE` on a server: the defaults are production and real mode.

## Limits and honest notes

* `.env.production` holds every secret in one file. It is git-ignored. On a server, keep it readable by you only
  (`chmod 600`).
* The tool server's daily search caps default to a low 10 per user and 25 total, to protect a small
  search quota. Raise them with `MCP_DAILY_CREDITS_PER_USER` / `MCP_DAILY_CREDITS_GLOBAL` in `.env.production`.
* No backups are configured. The database lives in a Docker volume on that one machine.
* Jaeger/Prometheus/Grafana are not part of this layout (see docs/observability.md for the local stack).
* In demo mode the Buy button opens an empty tab (the mock links go nowhere).
