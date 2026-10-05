# Appendix B. Cheat Sheets

Quick references. Commands assume the repo root unless stated. **Never print secret values**: list names only.

---

## B.1 Environment variable reference (this project)

Where each variable is read, its default, and whether it is a secret. "API" = `services/api/src/api/config.py`; "MCP" = `services/mcp/src/mcp_server/config.py`; "Compose" = interpolated by Docker Compose; "Build" = consumed at image build.

### API service

| Variable | Default (code) | Secret? | Purpose |
|---|---|---|---|
| `DATABASE_URL` | `postgresql://stylist:stylist_dev_password@localhost:5432/stylist` | **yes** (password) | Postgres connection (host `postgres` inside Docker) |
| `STYLIST_MODEL` | `opencode/gpt-5.5` (`.env.example`: `openrouter/apodex/apodex-1.1-mini:free`) | no | `<provider>/<model-id>` |
| `OPENROUTER_API_KEY`, `OPENCODE_API_KEY` | empty | **yes** | model gateway keys |
| `OPENROUTER_BASE_URL`, `OPENCODE_BASE_URL` | gateway URLs | no | endpoints |
| `LLM_API_MODE` | empty | no | force `chat` or `responses` endpoint style (opencode) |
| `STRUCTURED_OUTPUT_METHOD` | `function_calling` | no | `json_schema` / `function_calling` / `json_mode` |
| `FORCE_IPV4` | `true` | no | avoid IPv6 stall |
| `MCP_URL` | `http://127.0.0.1:8001/mcp` | no | tool-server address (compose: `http://mcp:8001/mcp`) |
| `MCP_JWT_PRIVATE_KEY` | empty | **yes** | signs tool-server tokens (API only) |
| `MCP_JWT_ISSUER` / `MCP_JWT_AUDIENCE` | `stylist-api` / `stylist-mcp` | no | token claims |
| `MCP_JWT_TTL_S` | `30` | no | tool-token lifetime |
| `AUTH_JWT_PRIVATE_KEY`, `AUTH_JWT_PUBLIC_KEY` | empty | **private: yes** | user access-token keys |
| `AUTH_JWT_ISSUER` / `AUTH_JWT_AUDIENCE` | `stylist-api` / `stylist-web` | no | claims |
| `AUTH_ACCESS_TTL_S` | `900` | no | access token life (15 min) |
| `AUTH_REFRESH_TTL_S` | `1209600` | no | refresh token life (14 d) |
| `AUTH_JWT_LEEWAY_S` | `10` | no | clock-skew tolerance |
| `WEB_ORIGIN` | `http://localhost:3000` | no | CORS origin (prod: `PUBLIC_URL`) |
| `COOKIE_SECURE` | `false` (image sets `true`) | no | `Secure` flag on refresh cookie |
| `LOGIN_MAX_FAILURES` / `LOGIN_WINDOW_S` | `5` / `900` | no | login lockout |
| `CHAT_MESSAGES_PER_MIN` | `10` | no | per-user chat limit |
| `DAILY_CONVERSATIONS_PER_USER` | `30` | no | new-conversation cap |
| `BUY_LINKS_PER_MIN` | `10` | no | per-user buy-link limit |
| `ADMIN_EMAILS` | empty | no | admin allow-list |
| `ENVIRONMENT` | `dev` (image: `prod`) | no | `prod` disables docs, refuses demo mode |
| `BACKEND_MODE` | `live` | no | `demo` = scripted model + mock search |
| `METRICS_TOKEN` | empty | **yes** | `/metrics` bearer token; empty = off |
| `FORWARDED_ALLOW_IPS` | (uvicorn default) | no | which peers may set `X-Forwarded-*` (prod compose: `*`, safe only because unpublished) |

### MCP tool server

| Variable | Default | Secret? | Purpose |
|---|---|---|---|
| `SERPAPI_API_KEY` | empty | **yes** | search provider key (MCP only in prod) |
| `MCP_JWT_PUBLIC_KEY` | empty (**server refuses to start without**) | no (public) | verifies API tokens |
| `MCP_JWT_ISSUER` / `MCP_JWT_AUDIENCE` | `stylist-api` / `stylist-mcp` | no | expected claims |
| `MCP_JWT_LEEWAY_S` / `MCP_JWT_MAX_LIFETIME_S` | `10` / `60` | no | skew tolerance / lifetime cap |
| `MCP_RATE_LIMIT_PER_MIN` | `60` | no | per-user calls/min |
| `MCP_DAILY_CREDITS_PER_USER` / `MCP_DAILY_CREDITS_GLOBAL` | `40` / `100` (prod compose: `10` / `25`) | no | paid-search caps |
| `MCP_ALLOWED_HOSTS` | empty | no | accepted `Host` names (compose: `mcp`) |
| `MCP_HOST` / `MCP_PORT` | `127.0.0.1` / `8001` | no | bind address (compose: `0.0.0.0`) |
| `SERPAPI_BASE_URL` | `https://serpapi.com/search.json` | no | |
| `SEARCH_CACHE_TTL_S` | `21600` | no | search/ref/link cache life (6 h) |
| `METRICS_TOKEN` | empty | **yes** | `/metrics` auth |
| `FORCE_IPV4` | `true` | no | |

### Compose, proxy, build, tools

| Variable | Where | Purpose |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Compose | database bootstrap and URL assembly (prod: password required) |
| `SITE_ADDRESS` | Compose → Caddy | `:80` local, hostname for automatic HTTPS |
| `HTTP_PORT` / `HTTPS_PORT` | Compose | host ports for Caddy (laptop: 8080) |
| `PUBLIC_URL` | Compose → API `WEB_ORIGIN` | public address of the site |
| `API_UPSTREAM` / `WEB_UPSTREAM` | Caddy | upstream override (default `api:8000`, `web:3000`) |
| `NEXT_PUBLIC_API_URL` | **Build** (web image) | API base URL baked into JS; empty = same origin |
| `GRAFANA_ADMIN_PASSWORD` | Compose (dev observability) | Grafana admin |
| `STYLIST_API_URL`, `EVAL_USERS`, `EVAL_USER_EMAIL`, `EVAL_USER_PASSWORD`, `OTEL_TRACES_ENDPOINT`, `OTEL_SERVICE_NAME`, `MASTRA_DATA_DIR` | Mastra app | evals/tracing (allow-listed loader; no model/search keys) |
| `IMAGE_PROVIDER`, `IMAGE_MODEL` | reserved | image features not built |

### Which file gets which

* `.env.example`: all names, no secrets, committed. `.env`: local real values (git-ignored). `.env.production`: prod stack via `--env-file`. `infra/observability/.secrets/metrics_token`: Prometheus secret file. See Chapter 1b.

## B.2 Git

```bash
git status; git diff; git diff --staged; git add -p; git commit -m "msg"
git switch -c feat/x; git switch main; git merge feat/x; git rebase main
git log --oneline --graph -20; git show <sha>; git blame file; git log -S"text"
git restore file; git restore --staged file; git stash; git stash pop
git revert <sha>; git reset --soft HEAD~1; git reflog; git cherry-pick <sha>
git bisect start; git bisect bad; git bisect good <sha>; git bisect reset
git check-ignore -v .env; git ls-files --others --exclude-standard
git push -u origin branch; git push --force-with-lease    # never force-push main
```

## B.3 Docker and Compose

```bash
docker build -f services/api/Dockerfile -t stylist-api .          # repo-root context
docker run --rm -p 127.0.0.1:8000:8000 --env-file envfile stylist-api
docker ps -a; docker logs -f --tail=200 <c>; docker exec -it <c> sh; docker inspect <c>
docker stats; docker history <img>; docker system df; docker system prune     # prune carefully
docker compose up -d --build; docker compose ps; docker compose logs -f api
docker compose exec api sh; docker compose down; docker compose down -v      # -v DELETES volumes
docker compose --profile observability up -d
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T postgres pg_dump -U stylist stylist | gzip > backup.sql.gz
```

Hardening flags: `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: ["no-new-privileges:true"]`, `mem_limit`, `pids_limit`, non-root `USER`, exec-form `CMD`, no `ports:` for private services.

## B.4 Linux and shell

```bash
ls -la; cd; pwd; cat; less; head; tail -f; grep -rn "x" .; find . -name "*.py"; wc -l; sort | uniq -c | sort -rn
chmod 600 file; chown user:group file; umask 077; sudo; id
ps aux | grep x; top; htop; kill <pid>; kill -9 <pid>; free -h; df -h; df -i; du -sh *; ss -ltnp; lsof -i :8000
journalctl -u svc -f; systemctl status|restart|enable svc; crontab -e
curl -v URL; curl -N URL; curl -s URL | jq .; dig name; nc -vz host port; openssl s_client -connect host:443 -servername host
ssh user@host; ssh -L 9090:127.0.0.1:9090 user@host; scp; rsync -avz src/ user@host:/dst/
set -euo pipefail; trap cleanup EXIT; "$quote_every_variable"
```

## B.5 HTTP quick reference

* **Status**: 200 OK, 201 Created, 204 No Content, 301/302/307/308 redirects, 400 Bad Request, 401 Unauthenticated, 403 Forbidden, 404 Not Found, 409 Conflict, 421 Misdirected, 422 Validation, 429 Too Many Requests (+`Retry-After`), 500, 502 Bad Gateway, 503, 504 Gateway Timeout.
* **Methods**: GET, HEAD, OPTIONS (safe); PUT, DELETE (idempotent); POST, PATCH (not).
* **Headers**: `Authorization: Bearer`, `Content-Type`, `Accept`, `Cache-Control`, `Set-Cookie`, `Origin`, `Host`, `X-Forwarded-For`, `Retry-After`, `traceparent`.
* **Cookie flags**: `HttpOnly; Secure; SameSite=Strict; Path=/auth; Max-Age=...`
* **SSE**: `event: name\ndata: {json}\n\n`; headers `Content-Type: text/event-stream`, `Cache-Control: no-cache`.

## B.6 curl against this API

```bash
BASE=http://localhost:8000
curl -s -c jar.txt -H 'Content-Type: application/json' -d '{"email":"me@example.com","password":"a long passphrase 123"}' $BASE/auth/register
curl -s -b jar.txt -X POST -H 'X-Requested-With: stylist-web' $BASE/auth/refresh
curl -s -X POST -H "Authorization: Bearer $TOKEN" $BASE/conversations
curl -N -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"text":"College wear, around 4000"}' $BASE/conversations/$ID/messages
curl -s -H "Authorization: Bearer $TOKEN" $BASE/conversations/$ID
```

## B.7 SQL (Postgres)

```sql
SELECT ... FROM a JOIN b ON ... WHERE ... GROUP BY ... HAVING ... ORDER BY ... LIMIT n;
INSERT INTO t (a,b) VALUES (%s,%s) RETURNING id;
INSERT ... ON CONFLICT (k) DO UPDATE SET n = t.n + 1;
WITH x AS (SELECT ...) SELECT ... FROM x;
SELECT id, rank() OVER (PARTITION BY user_id ORDER BY total_inr DESC) FROM outfits;
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
SELECT ... FOR UPDATE;                 SELECT pg_advisory_lock(1);
CREATE INDEX CONCURRENTLY idx ON t (a, b DESC);
-- psql: \dt  \d+ table  \di  \x  \timing  \q
```

## B.8 Python and pytest idioms

```python
from dataclasses import dataclass, field; from pydantic import BaseModel, Field, field_validator, ConfigDict
from collections import deque, defaultdict, Counter, OrderedDict; import heapq, bisect, itertools, functools
with pool.connection() as conn: ...            # commit on success, rollback on exception
@contextmanager; async with; yield; asyncio.run(); ThreadPoolExecutor(max_workers=8)
secrets.token_urlsafe(48); hmac.compare_digest(a, b); hashlib.sha256(b).hexdigest()
uv sync --frozen; uv run pytest -q -x -k name; uv run ruff check .
@pytest.fixture; @pytest.mark.parametrize("x,y", [...]); pytest.raises(E, match="..."); monkeypatch.setenv(...)
```

## B.9 TypeScript / JavaScript idioms

```ts
const x = a ?? b; a?.b; a ??= b          // nullish
async function* gen() { yield 1 }        // async generator;  for await (const v of gen()) {}
type U = { kind: 'a'; a: number } | { kind: 'b'; b: string }     // discriminated union
setItems((s) => [...s, item])             // immutable state update
useEffect(() => { ...; return () => cleanup() }, [deps])
npm ci -w apps/web; npm test -w apps/web; npm run typecheck -w apps/web
```

## B.10 Big-O and structure picker

| Structure | Access | Search | Insert | Delete | Use |
|---|---|---|---|---|---|
| list | O(1) | O(n) | O(1) end / O(n) | O(n) | sequences |
| dict / set | – | O(1) avg | O(1) avg | O(1) avg | lookup, dedupe |
| deque | O(1) ends | O(n) | O(1) ends | O(1) ends | queues, windows |
| heap | O(1) top | O(n) | O(log n) | O(log n) | top-k, scheduling |
| sorted list + bisect | O(1) | O(log n) | O(n) | O(n) | ordered queries |
| BST (balanced) / B-tree | | O(log n) | O(log n) | O(log n) | ordered maps, indexes |
| trie | | O(len) | O(len) | O(len) | prefixes |
| graph (adj list) | | O(V+E) traversal | O(1) | | relationships |

Sorting O(n log n); binary search O(log n); BFS/DFS O(V+E); Dijkstra O((V+E) log V).

## B.11 JWT quick card

`header.payload.signature` (Base64url). Claims: `iss, sub, aud, exp, nbf, iat, jti`. **Always**: pin `algorithms=["RS256"]`; require `exp/iat/sub/iss/aud`; verify `aud` and `iss`; small leeway; cap lifetime; use `jti` for single-use; separate keys per purpose; never put secrets in the payload.

## B.12 PromQL

```promql
sum by (route) (rate(stylist_http_requests_total[5m]))
sum(rate(stylist_http_requests_total{status=~"5.."}[5m])) / sum(rate(stylist_http_requests_total[5m]))
histogram_quantile(0.95, sum by (le) (rate(stylist_chat_turn_seconds_bucket[5m])))
increase(mcp_search_credits_spent_total[24h])
sum by (limiter) (increase(stylist_rate_limited_total[1h]))
```

## B.13 Common ports

22 SSH · 80 HTTP · 443 HTTPS · 5432 Postgres · 6379 Redis · 8000 API · 8001 MCP · 3000 web (Next) · 3001 Grafana (host) · 9090 Prometheus · 16686 Jaeger UI · 4318 OTLP/HTTP · 4111 Mastra Studio · 8080 laptop Caddy (prod test).

## B.14 Decision one-liners

* Workflow before agent. Prompt before RAG before fine-tune. Code before model for exact work.
* Verify, do not trust. Fail closed. Least privilege. One public door.
* Measure before optimising. Bound every loop. Log names, not secrets.
* Build bottom-up and prove each connection.
