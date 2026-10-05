# Chapter 16. Networking and the Web

> **Learning objectives.** Understand how data moves between a browser, a proxy, your services and the internet (IP, DNS, TCP, TLS, HTTP); design and consume REST-style APIs; stream with SSE; reason about the browser security model (same-origin policy, CORS, cookies, CSRF); understand proxies, forwarded headers and Docker networking; and debug network problems with the right tools. Every concept is tied to a line of this repo.
>
> **Prerequisites.** Chapter 2.

Most "AI app" bugs that are not model bugs are **network bugs**: a service that cannot reach another, a cookie that is not sent, a stream that arrives all at once, a certificate that fails, a request that hangs 40 seconds on IPv6. This chapter builds the mental model to diagnose them.

---

## 16.1 Layers: how a message travels

Networks are described in layers, each using the one below:

| Layer | Job | Examples |
|---|---|---|
| **Application** | the meaning of the conversation | HTTP, DNS, SMTP, gRPC, MCP over HTTP |
| **Security** | confidentiality and authenticity | TLS (HTTPS) |
| **Transport** | reliable (or fast) delivery between *programs* (ports) | TCP, UDP, QUIC |
| **Internet** | addressing and routing between *machines* | IP (IPv4, IPv6) |
| **Link** | one hop over a physical medium | Ethernet, Wi-Fi |

Data is split into **packets**; each carries source and destination addresses; routers forward them hop by hop. A **port** (0-65535) selects the program on a machine; a **socket** is (address, port) at each end. A **server** *listens* on a port (`uvicorn` on 8000, Caddy on 80/443, Postgres on 5432, the MCP server on 8001); a **client** connects from a temporary (ephemeral) port.

## 16.2 IP addresses and what the special ones mean

* **IPv4**: 32 bits (`203.0.113.7`); **IPv6**: 128 bits (`2001:db8::1`).
* **Private ranges** (not routable on the internet): `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`. Home routers and **Docker networks** use them.
* **Loopback**: `127.0.0.1` / `::1` / `localhost`: "this machine only".
* **Link-local**: `169.254.0.0/16`: automatic addressing; **cloud providers expose an instance metadata service at `169.254.169.254` that can hand out credentials**, which is why SSRF defences block it (Chapter 21).
* **`0.0.0.0`**: as a *listen* address means "all interfaces" (reachable from outside the machine/container). As an *outbound source* address (`httpx.HTTPTransport(local_address="0.0.0.0")`) it forces the **IPv4** family, which is how this repo avoids the IPv6 stall.
* **CIDR notation**: `10.0.0.0/8` = first 8 bits are the network. Useful for firewalls and allow-lists.
* **NAT** lets many private hosts share one public address; **the client IP your server sees may be the proxy's or the NAT's** (Section 16.9).

Python's `ipaddress` module encodes this knowledge, and `check_link` uses it: `ip.is_global` (publicly routable) excludes private, loopback, link-local and reserved ranges.

### The 40-second IPv6 stall

Many hostnames have both AAAA (IPv6) and A (IPv4) records. A client that tries IPv6 first on a network where IPv6 is advertised but broken waits for a timeout (tens of seconds) before falling back. Symptoms: *the first request hangs ~40 s, then everything is fast.* The repo's `force_ipv4` setting (default true) pins outbound connections to IPv4. Real-world FDE lesson: **customer networks have quirks; test on them early.**

## 16.3 DNS: names to addresses

**DNS** translates `api.example.com` to IP addresses.

* **Records**: `A` (IPv4), `AAAA` (IPv6), `CNAME` (alias to another name), `MX` (mail), `TXT` (arbitrary: domain verification, SPF), `NS` (name servers), `CAA` (which CAs may issue certificates).
* **Resolution**: your machine asks a **recursive resolver** (ISP/corporate/8.8.8.8), which asks root → TLD (`.com`) → the domain's authoritative servers, **caching** answers for the record's **TTL**.
* **TTL**: how long answers may be cached; low TTL = faster changes, more queries. Changing DNS "takes time" because of cached copies.
* **Docker's embedded DNS** resolves **service names** on a compose network: from the API container, `postgres` and `mcp` are hostnames (`postgresql://...@postgres:5432/...`, `http://mcp:8001/mcp`). That is why `MCP_ALLOWED_HOSTS: mcp` works.
* **Free hostnames without a domain**: `203-0-113-7.sslip.io` resolves to `203.0.113.7`: a wildcard DNS service. The deployment guide uses it so Caddy can obtain a real certificate for a raw IP.
* **DNS rebinding** (an attack): an attacker's domain first answers with a public IP (passing a check) and a moment later with `127.0.0.1` (when the victim connects). Defences in this repo: the tool server **validates the `Host` header** (browser-sent requests carry the attacker's hostname, so they are refused with 421), and `check_link` **resolves once, checks the address, then connects to that exact IP**.

## 16.4 TCP, UDP and TLS

### TCP

**Transmission Control Protocol**: reliable, ordered byte stream. Connection starts with a **three-way handshake** (SYN, SYN-ACK, ACK = one round trip), uses acknowledgements and retransmission, and has flow and congestion control. Costs: handshake latency, head-of-line blocking. **Connection reuse (keep-alive, pooling)** avoids repeated handshakes (Chapter 14).

### UDP and QUIC

**UDP** is connectionless and unreliable but low-latency (DNS, video, games). **QUIC** (the basis of HTTP/3) builds reliable multiplexed streams over UDP with built-in TLS.

### TLS (HTTPS)

**Transport Layer Security** provides **encryption**, **integrity** and **server authentication** over TCP. The handshake:

1. **ClientHello**: supported versions/ciphers, a random value, and the **SNI** (Server Name Indication: *which hostname* the client wants; lets one IP serve many sites).
2. **ServerHello + certificate chain**: the server proves its identity with an **X.509 certificate** signed by a **Certificate Authority (CA)** that the client trusts.
3. **Key exchange** (ephemeral Diffie-Hellman) derives shared session keys with **forward secrecy** (recording traffic and later stealing the server key does not decrypt it).
4. Encrypted application data flows.

The client **verifies**: the chain leads to a trusted root; the certificate is currently valid (**clock matters**: a wrong system clock breaks TLS, just as it can break JWT validation); and the **certificate's name matches the host the client asked for**.

* **Let's Encrypt / ACME**: free, automated certificates. **Caddy** obtains and renews them on its own when `SITE_ADDRESS` is a real domain ("Caddy fetches the https certificate by itself on first visit"), storing them in the `caddy_data` volume so restarts do not re-request (and hit rate limits).
* **HSTS** (`Strict-Transport-Security: max-age=31536000`, set in the Caddyfile): tells browsers to *only ever use HTTPS* for this site for a year, defeating downgrade attacks.
* **mTLS** (mutual TLS): the client also presents a certificate; a strong service-to-service identity option (this repo uses signed JWTs instead).
* **SNI + IP pinning in `check_link`**: the tool connects to the *already-checked IP address* but still sends the real hostname as the `Host` header and `sni_hostname` extension, so **certificate verification still validates the real name**: you get rebinding protection *without* weakening TLS.
* **TLS termination**: Caddy terminates TLS; traffic to `api` and `web` inside the Docker network is plain HTTP over a private bridge. Acceptable for a single host; across hosts or untrusted networks you would encrypt internal hops too.
* **Common TLS failures**: expired/self-signed certificate, name mismatch, missing intermediate certificates, clock skew, corporate proxies that re-sign traffic, protocol mismatches.

## 16.5 HTTP in depth

### A request and response

```
POST /conversations/7f2c.../messages HTTP/1.1
Host: localhost:8080
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
Content-Type: application/json
Accept: text/event-stream
traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01

{"text": "College wear, around ₹4000"}
```

```
HTTP/1.1 200 OK
content-type: text/event-stream; charset=utf-8
cache-control: no-cache
x-accel-buffering: no
x-request-id: 3a9f0c1b2d4e5f60
x-trace-id: 4bf92f3577b34da6a3ce929d0e0e4736

event: status
data: {"stage": "gather_prefs", "label": "Understood your request", ...}

```

Parts: **start line** (method + path / status), **headers**, blank line, **body**.

### URLs

`https://user@host.example.com:8443/path/to/resource?x=1&y=2#fragment`: scheme, authority (userinfo, host, port), path, query, fragment (never sent to the server). **Percent-encoding** escapes unsafe characters (`encodeURIComponent` in `api.ts` for `product_id`). **Parsing URLs is a security-critical operation** (`urlparse(...).hostname` in `check_link`), and parser differences between components cause SSRF bugs, so use one parser consistently.

### Methods and their semantics

| Method | Meaning | Safe (no side effects) | Idempotent |
|---|---|---|---|
| GET | read | yes | yes |
| HEAD | headers only | yes | yes |
| POST | create / perform an action | no | **no** |
| PUT | replace | no | yes |
| PATCH | partial update | no | not guaranteed |
| DELETE | remove | no | yes |
| OPTIONS | capabilities (CORS preflight) | yes | yes |

Why it matters: **clients, proxies and browsers retry idempotent requests automatically**; a non-idempotent POST needs an **idempotency key** or other protection.

### Status codes (memorise the families and the common ones)

* **1xx** informational. **2xx** success: 200 OK, 201 Created (register, create conversation), 204 No Content (logout).
* **3xx** redirect: 301/308 permanent, 302/307 temporary, 304 Not Modified. (`check_link` follows redirects *manually* and re-validates every hop.)
* **4xx client error**: 400 Bad Request, **401 Unauthorized** (not authenticated), **403 Forbidden** (authenticated but not allowed; also the CSRF header check), **404 Not Found** (this API also uses 404 to *hide existence*: someone else's conversation, a product you were not shown, an admin route for non-admins), 405, 409 Conflict (email taken; turn already running), 413, 415, **421 Misdirected Request** (the MCP server's refusal of a foreign `Host`), 422 Unprocessable (validation: weak password, bad email), **429 Too Many Requests** (with `Retry-After`).
* **5xx server error**: 500 internal, **502 Bad Gateway** (an upstream returned garbage or is unreachable), 503 Service Unavailable, **504 Gateway Timeout** (an upstream took too long). The buy-link route returns 502/503 deliberately: *the store/tool upstream failed, not us.*

A habit that pays off: **be consistent and deliberate with status codes**, and keep error bodies uniform (`{"detail": "..."}`), safe to show.

### Headers worth knowing

| Header | Purpose |
|---|---|
| `Host` | which site (virtual hosting); security-relevant (rebinding) |
| `Authorization: Bearer <token>` | credentials |
| `Content-Type`, `Accept` | body format negotiation |
| `Cache-Control` | caching rules (`no-store` on `/auth/*` so tokens never sit in a cache; `no-cache` on the SSE stream) |
| `Set-Cookie`, `Cookie` | cookies (below) |
| `Origin`, `Referer` | where a request comes from (CORS, CSRF checks, the MCP `Origin` guard) |
| `X-Forwarded-For`, `X-Forwarded-Proto`, `Forwarded` | original client info through proxies |
| `Retry-After` | when to retry (429/503) |
| `traceparent`, `X-Request-ID`, `X-Trace-Id` | correlation (Chapter 13) |
| `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy` | browser hardening (the API sets the first four classes; CSP is not set, an honest gap) |
| `User-Agent` | client identity (`check_link` sends a browser-like one to avoid trivial bot blocks) |

### HTTP versions

* **HTTP/1.1**: text, one request at a time per connection (browsers open ~6 connections per host), keep-alive.
* **HTTP/2**: binary, **multiplexes** many streams over one connection, header compression.
* **HTTP/3**: over QUIC; fixes TCP head-of-line blocking.

Caddy speaks HTTP/2 and HTTP/3 to browsers automatically; internal hops use HTTP/1.1.

### Streaming bodies

A response without a known length uses **chunked transfer encoding** (HTTP/1.1) or data frames (HTTP/2): the server sends pieces as ready. This is how SSE and the streaming chat endpoint work. Note: **compression and buffering** (in proxies, CDNs, or middlewares) can accumulate chunks and deliver them at once, which defeats streaming. Hence `X-Accel-Buffering: no` (an nginx convention), `Cache-Control: no-cache`, and in Caddy `flush_interval -1`.

## 16.6 Designing and consuming APIs

### REST principles (pragmatic version)

* **Resources as nouns** with stable URLs: `/conversations`, `/conversations/{id}`, `/conversations/{id}/messages`, `/products/{id}/buy-link`.
* **Verbs via HTTP methods**; actions that do not fit become sub-resources (`POST /products/{id}/buy-link`, `POST /auth/refresh`).
* **Stateless requests**: every request carries its own credentials; state lives in storage.
* **Consistent errors**, **correct status codes**, **pagination** for lists (`list_conversations` has `limit=30`), **filtering**, **versioning** (`/v1/...` or headers) when clients are not under your control, **idempotency keys** for retried POSTs, **rate limit headers**.
* **Validate everything** at the boundary; never trust path ids (`_valid_id` converts to UUID or returns 404).
* **Authorise every object access** (ownership checks), not just authenticate.
* **OpenAPI**: FastAPI generates a machine-readable spec and interactive docs at `/docs` in development (disabled in production by `docs_url=None`, `openapi_url=None`). A spec gives you client generation, contract tests and tool definitions for agents.

### This API's surface

| Method & path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | liveness |
| `GET /metrics` | bearer `METRICS_TOKEN` (404 if unset) | Prometheus |
| `POST /auth/register`, `/auth/login` | none (+ IP limit; lockout on login) | create account / sign in |
| `POST /auth/refresh`, `/auth/logout` | refresh cookie + `X-Requested-With: stylist-web` | rotate token / sign out |
| `GET /auth/me` | access token | who am I |
| `POST /conversations`, `GET /conversations`, `GET /conversations/{id}` | access token | create/list/read |
| `POST /conversations/{id}/messages` | access token (+ chat limit) | send a message; **SSE stream** |
| `POST /products/{id}/buy-link` | access token (+ ownership + limit) | store link + liveness |
| `GET /admin/audit/verify` | admin (404 otherwise) | verify the audit chain |

### Trying it with curl

```bash
BASE=http://localhost:8080          # via Caddy (prod layout); use :8000 for the dev API
curl -s -c jar.txt -H 'Content-Type: application/json' \
  -d '{"email":"me@example.com","password":"a long passphrase 123"}' $BASE/auth/register
# -> {"access_token":"eyJ...","token_type":"bearer","expires_in":900}   and a refresh cookie saved in jar.txt

TOKEN=eyJ...
ID=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" $BASE/conversations | python -c 'import sys,json;print(json.load(sys.stdin)["id"])')

curl -N -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"College wear, around 4000 rupees"}' $BASE/conversations/$ID/messages
# -N = no buffering: watch the events arrive one at a time

curl -s -b jar.txt -X POST -H 'X-Requested-With: stylist-web' $BASE/auth/refresh     # rotates the cookie
```

### Other API styles

| Style | Idea | Use |
|---|---|---|
| **REST/JSON over HTTP** | resources + methods | public and general-purpose APIs (this app) |
| **GraphQL** | the client asks for exactly the fields it needs through one endpoint | complex UIs with many relationships; needs query cost limits |
| **gRPC** | binary Protocol Buffers over HTTP/2, strongly typed, streaming | internal service-to-service, high throughput |
| **JSON-RPC** | named methods with JSON | MCP uses it |
| **WebSocket** | persistent two-way channel | chat, collaboration, games |
| **Webhooks** | the server calls *you* when something happens | payment/CI events (verify signatures, be idempotent) |

## 16.7 Real-time patterns: polling, SSE, WebSockets

| Pattern | Direction | Works through proxies | Notes |
|---|---|---|---|
| **Polling** | client asks repeatedly | trivially | wasteful and laggy |
| **Long polling** | server holds the request until data | yes | simple fallback |
| **Server-Sent Events (SSE)** | **server → client**, one long response | yes (plain HTTP) | text format, auto-reconnect in `EventSource` |
| **WebSocket** | **both ways**, upgraded connection | mostly (needs proxy support) | binary/text, you manage reconnection |

**Why this app uses SSE over `fetch`:** the agent's turn is one-way streaming progress over a POST (to send the message). The browser's built-in `EventSource` **cannot POST or send an `Authorization` header**, so the client reads the response body itself (`ReadableStream` + a small parser, `lib/sse.ts`).

### The SSE wire format

```
event: status
data: {"stage": "propose_styles", "label": "Styles ready"}

event: outfits
data: {"outfits": [...]}

```

Rules: lines of `field: value`; fields `event`, `data`, `id`, `retry`; a **blank line ends an event**; lines starting with `:` are comments (used as **heartbeats** to keep idle connections alive). The server helper:

```python
def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
```

with the comment: *"JSON never contains a raw newline, so the framing cannot be broken by anything inside the data."* Injecting a blank line into the data would otherwise let user content forge new events (an injection bug class, again: **framing must not be controllable by data**).

### Production concerns for streams

* **Proxy buffering and idle timeouts**: ensure proxies flush (`flush_interval -1`), and consider sending periodic comment heartbeats if a stage can be silent longer than an intermediary's idle timeout (cloud load balancers often cut idle connections at 60 s). This app's stages emit events as they finish; a very slow stage is a risk.
* **Client disconnects**: the server's generator is closed and the `finally` block releases the conversation lock (Chapter 2). The graph keeps its checkpoints, so the user can reload and see state.
* **Resumption**: SSE supports `id` and `Last-Event-ID` for resume; this app instead lets the client fetch the full conversation (`GET /conversations/{id}`) to recover, a simpler design because the final state is persisted.
* **Backpressure**: if the client reads slowly, buffers fill; keep events small.
* **Scaling**: each open stream occupies a connection and (here) a worker thread; model concurrency limits accordingly (Chapter 5, Little's Law).

## 16.8 The browser security model

### Origin and same-origin policy

An **origin** = scheme + host + port. `http://localhost:3000` and `http://localhost:8000` are **different origins**. The **same-origin policy** stops a page from one origin from *reading* responses from another. (It does not stop the browser from *sending* requests, which is why CSRF exists.)

### CORS (Cross-Origin Resource Sharing)

The server can *opt in* to cross-origin reads with response headers. For "non-simple" requests (JSON `Content-Type`, custom headers like `Authorization`), the browser first sends a **preflight** `OPTIONS` asking permission. This API:

```python
app.add_middleware(CORSMiddleware, allow_origins=[cfg.web_origin], allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "traceparent", "X-Trace-Id"],
    expose_headers=["X-Request-ID", "X-Trace-Id"])
```

* **An explicit origin list**, never `*` together with credentials (browsers refuse the combination; `*` would be unsafe anyway).
* **`allow_credentials=True`** lets the browser send cookies cross-origin (the refresh cookie) in the dev setup (UI on 3000, API on 8000).
* **`expose_headers`** makes custom response headers readable by JavaScript.
* **In the hosted layout CORS is not needed**: Caddy serves UI and API from **one origin**, so the browser sees "same site", cookies work without extra settings, there is no cross-site traffic to secure, and no domain purchase is needed. *Architecture can remove a whole class of problems.*
* CORS is a **browser** rule. It does **not** protect your API from `curl` or scripts; authentication does that.

### Cookies

A cookie is a small value the server asks the browser to store and send back. Attributes:

| Attribute | Effect | The refresh cookie |
|---|---|---|
| `HttpOnly` | JavaScript cannot read it (defends against XSS stealing it) | **yes** |
| `Secure` | sent only over HTTPS | **yes in production** (`COOKIE_SECURE=true`) |
| `SameSite=Strict` | sent only for same-site requests (defends against CSRF) | **yes** |
| `Path=/auth` | sent only to `/auth/*` (limits exposure) | **yes** |
| `Max-Age` | lifetime (14 days) | yes |
| `Domain` | which hosts get it (omitted = just this host) | omitted |

*Site* (registrable domain, e.g. `example.com`) differs from *origin*; `SameSite` is about **site**.

**Where to keep tokens in the browser** (a favourite interview debate): `localStorage` is readable by any script on the page (XSS steals it); `HttpOnly` cookies cannot be read by scripts but are sent automatically (CSRF risk, mitigated by SameSite and a custom header). This app's compromise: the **short-lived access token lives only in a JavaScript variable (memory)**, sent in the `Authorization` header (not auto-sent, so no CSRF); the **long-lived refresh token is an HttpOnly, SameSite=Strict, Path-scoped cookie** that scripts cannot read. A page reload loses the in-memory token, so the app silently calls `/auth/refresh` to get a new one.

### CSRF in one paragraph

**Cross-Site Request Forgery**: a malicious site makes your browser send a request to a site where you are logged in, and the browser attaches your cookies automatically. Defences: `SameSite` cookies; **requiring a custom header** (`X-Requested-With: stylist-web`) on cookie-authenticated endpoints, because a cross-site page cannot add custom headers without a CORS permission you never grant (that is the `_require_csrf_header` check on `/auth/refresh` and `/auth/logout`); CSRF tokens; checking `Origin`. Endpoints authenticated by an `Authorization` header (not cookies) are not CSRF-prone.

### Other browser protections

`X-Content-Type-Options: nosniff` (do not guess MIME types), `X-Frame-Options: DENY` (cannot be framed: clickjacking), `Referrer-Policy: no-referrer`, **CSP** (restrict where scripts load from: strong XSS mitigation; not yet configured), `rel="noopener"` for `window.open` (the Buy button sets `tab.opener = null`), **sandboxed iframes**, **subresource integrity**.

## 16.9 Proxies, forwarded headers and load balancing

A **reverse proxy** sits in front of servers and forwards requests: TLS termination, routing by path/host, compression, caching, rate limiting, load balancing, hiding internals. A **forward proxy** sits in front of *clients* (corporate proxies). **Load balancers** distribute traffic across instances (L4 by connection, L7 by HTTP request) with **health checks**.

### Routing in this repo (Caddy)

```
@api path /auth/* /conversations /conversations/* /products/* /admin/* /health
handle @api { reverse_proxy {$API_UPSTREAM:api:8000} { flush_interval -1 } }
handle     { reverse_proxy {$WEB_UPSTREAM:web:3000} }
```

An **allow-list** of API paths: everything else goes to the web app. **`/metrics` is deliberately not routed**, so it cannot be reached from outside. *The proxy's route list is part of your security perimeter.*

### Who is the client? `X-Forwarded-For`

Behind a proxy, the TCP peer the API sees is **the proxy**, so IP-based rate limiting would treat all users as one. The proxy therefore sends `X-Forwarded-For: <real client>`. **Trusting that header blindly is dangerous**: anyone can send a fake one directly. uvicorn's `--proxy-headers` plus `FORWARDED_ALLOW_IPS` says *which peers may set it*. In `docker-compose.prod.yml`, `FORWARDED_ALLOW_IPS: "*"` is set with the justification *"caddy (the only thing that can reach this container) tells the API each visitor's real address"*. That is safe **only because the API has no published port**; if the API were reachable directly, `*` would let attackers spoof their IP and dodge IP limits. (And the dev compose does not set it; `client_ip` has a comment: "Behind a proxy this would be the proxy's address; reading X-Forwarded-For is only safe when the proxy is trusted, so that is configured at deployment time, not assumed here.")

### Health checks and graceful behaviour

`/health` returns only `{"status": "ok"}`. Container `HEALTHCHECK`s and compose `depends_on: condition: service_healthy` use it, so dependents start only when ready, and orchestrators can restart sick containers.

## 16.10 Networking in Docker and Compose

* Each compose project gets a **private bridge network** with DNS for service names.
* **`ports: ["8000:8000"]`** *publishes* a container port on the **host** (reachable from outside the machine unless bound to `127.0.0.1`). A service with **no `ports:`** is reachable **only** from other containers on the network (the MCP server, Postgres in prod, API and web in prod).
* **`127.0.0.1:9090:9090`** binds a published port to the host's loopback, so only that machine can reach it (Prometheus, Grafana, Jaeger admin UIs).
* **Inside a container, `localhost` is the container itself**, not your laptop or another container: a classic bug source. Use service names (`postgres`, `mcp`) between containers, and **`host.docker.internal`** (with `extra_hosts: host-gateway` on Linux) to reach the host, as Prometheus does to scrape an API running with plain `uvicorn`.
* **Binding to `0.0.0.0` inside a container** is normal (so other containers can connect); safety comes from *not publishing the port* and from the app's own `Host` allow-list (`MCP_ALLOWED_HOSTS: mcp`), plus `assert_safe_bind` refusing a non-loopback bind without it.
* **Network aliases/isolation**: put services on separate networks to control who can talk to whom (a stricter design than this single-network setup: for example, the web container could be denied access to Postgres).

## 16.11 A debugging toolbox

| Question | Tool |
|---|---|
| Is it reachable? What does it return? | `curl -v URL` (shows TLS, headers); `curl -N` for streams; `curl -i`; `--resolve host:port:ip` to test a specific IP |
| What does DNS say? | `dig example.com`, `nslookup`, (PowerShell) `Resolve-DnsName` |
| Is a port open? | `nc -vz host port`, (PowerShell) `Test-NetConnection host -Port 443` |
| What is listening locally? | `ss -ltnp` / `netstat -ano` / `lsof -i :8000` |
| What path do packets take? | `traceroute` / `tracert` |
| What is in the TLS certificate? | `openssl s_client -connect host:443 -servername host` |
| What did the browser send/receive? | DevTools → Network tab (headers, timing, cookies, preflights), Console (CORS errors) |
| Packet-level truth | Wireshark / `tcpdump` |
| Inside the container network | `docker compose exec api sh` then `curl http://mcp:8001/health`; `docker network inspect` |
| Service logs | `docker compose logs -f api` |

A method: **go layer by layer**: DNS resolves? → port reachable? → TLS valid? → HTTP status and headers sensible? → application logs? Most outages are found by the first three.

### Typical symptoms and causes

| Symptom | Likely cause |
|---|---|
| Connection refused | nothing listening; wrong port; service not started; bound to 127.0.0.1 inside a container |
| Hangs then times out | firewall dropping packets; wrong IP; **IPv6 stall**; upstream too slow |
| `ERR_CERT_*` / SSL errors | expired, wrong name, missing chain, wrong system time |
| 502 from the proxy | upstream down/crashed or wrong upstream address |
| 504 | upstream slow beyond the proxy timeout |
| CORS error in the console | missing/incorrect `Access-Control-Allow-*`; credentials with `*`; preflight rejected |
| Cookie not sent | `SameSite`/`Secure`/`Path` mismatch; HTTP vs HTTPS; different site |
| SSE arrives all at once | proxy or middleware buffering/compression |
| 421 from the tool server | `Host` header not in `MCP_ALLOWED_HOSTS` |
| 401 on every call after a while | access token expired and refresh failed; clock skew |
| Works on laptop, fails in Docker | `localhost` meaning, missing env var, no published port |

## Common mistakes

* Confusing origin with site; assuming CORS protects the API.
* `Access-Control-Allow-Origin: *` with credentials or on private data.
* Trusting `X-Forwarded-For` from the open internet.
* Binding services to `0.0.0.0` and publishing them accidentally.
* Using `localhost` between containers.
* Putting long-lived tokens in `localStorage`.
* Proxy buffering that breaks streaming; no heartbeats on long silent streams.
* Retrying non-idempotent POSTs blindly.
* Leaking existence through different 403/404 responses (this API uses uniform 404s deliberately).

## Summary

* Messages travel through layers: DNS → TCP → TLS → HTTP; each has its own failure modes and tools.
* HTTP semantics (methods, idempotency, status codes, headers) drive correct API design and safe retries.
* SSE is a simple, proxy-friendly one-way stream; use `fetch` readers when you need POST and auth headers; make sure nothing buffers it and framing cannot be injected.
* The browser enforces origins, CORS, cookies and framing; design token storage and CSRF defences deliberately; a single origin removes many problems.
* Proxies terminate TLS and route; forwarded headers must be trusted only from trusted proxies.
* Docker networks give service-name DNS; published ports and bind addresses define exposure.

## Key terms

*IP, port, socket, DNS, TTL, TCP handshake, TLS, SNI, certificate, CA, HSTS, mTLS, HTTP method, idempotent, status code, header, chunked encoding, REST, SSE, WebSocket, origin, CORS, preflight, cookie, HttpOnly, SameSite, CSRF, reverse proxy, X-Forwarded-For, bridge network, published port.*

## Interview questions

1. What happens, step by step, when you type a URL and press Enter?
2. Difference between 401 and 403? Why does this API return 404 for some forbidden things?
3. Explain CORS. Why does it not protect your API from curl?
4. Where should a SPA store its tokens? Justify this app's choice.
5. What is CSRF and how does this app defend against it?
6. SSE vs WebSocket vs polling: when to use each?
7. Why can streaming break behind a proxy, and how do you fix it?
8. What is `X-Forwarded-For` and when is it safe to trust it?
9. Why does `localhost` not work between containers?
10. What is SNI and why does `check_link` set it while connecting to an IP address?

## Exercises

1. With `curl -v`, fetch your deployment's `/health` and read every header; then request `/metrics` and explain the result.
2. Open DevTools and record a chat turn: find the preflight (dev layout), the SSE response, the refresh call and the cookie attributes.
3. Break streaming on purpose: put an nginx in front with default buffering and observe; then fix it with the right headers.
4. Write a script that sends a fake `X-Forwarded-For` to the API directly (dev) and to Caddy (prod), and observe which one the rate limiter uses.
5. Use `openssl s_client` against a site and list the certificate chain, validity dates and SANs.
