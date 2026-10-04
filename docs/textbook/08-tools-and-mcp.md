# Chapter 8. Tool Use and the Model Context Protocol (MCP)

> **Learning objectives.** Understand why models need tools and how function calling works at the message level; design tools a model (or program) can use correctly; understand MCP (architecture, primitives, JSON-RPC, transports, auth); build and test an MCP server and client with FastMCP; and read `services/mcp` in this repo in full, including *why* a private tool server exists even though the LLM never picks the tools.
>
> **Prerequisites.** Chapters 6-7.

---

## 8.1 Why models need tools

A language model alone can only produce text. It cannot check today's price, read your database, send an email, run code, or verify a link. **Tools** are how a model-based system reaches the world: *the model decides what to do; your code actually does it.*

Tools give a system three things the model lacks:

1. **Fresh or private data** (search, databases, APIs).
2. **Exactness** (calculators, code execution, validators).
3. **Actions** (create a ticket, book, buy, deploy).

The cost: every tool is a new **attack surface** and a new **failure mode**. So the engineering goal is *useful tools with the smallest possible blast radius*.

## 8.2 Function calling: the mechanism

**Function calling** (a.k.a. tool use) is a protocol between your application and the model API:

1. You send the conversation **plus a list of tool definitions**: name, description, and a **JSON Schema** for the arguments.
2. The model either answers in text **or** replies with one or more **tool calls**: the tool name and arguments *as structured data* (it does not execute anything).
3. **Your code** validates the arguments, runs the tool, and sends the **result** back as a new message.
4. The model reads the result and continues: answers, or calls another tool. Repeat until it produces a final answer.

This is the **agent loop** in its simplest form (Chapter 9). The model never runs code; it only *asks*. That is why **all authorization, validation and limits live in your code**.

### Message formats

OpenAI-style (Chat Completions):

```json
// 1. your request includes:
"tools": [{"type": "function", "function": {
   "name": "search_products",
   "description": "Find men's clothing in India for ONE garment ...",
   "parameters": {"type": "object",
      "properties": {"item": {"type": "string"}, "max_price_inr": {"type": "integer"}},
      "required": ["item", "max_price_inr"]}}}]

// 2. the model answers with:
{"role": "assistant", "tool_calls": [{"id": "call_1", "type": "function",
   "function": {"name": "search_products", "arguments": "{\"item\":\"chinos\",\"max_price_inr\":2500}"}}]}
//   note: `arguments` is a JSON *string*: always parse it (and validate!)

// 3. you reply with:
{"role": "tool", "tool_call_id": "call_1", "content": "{\"results\": [...]}"}
```

Anthropic-style (Messages API):

```json
// the model answers with content blocks and stop_reason "tool_use":
{"role": "assistant", "content": [
   {"type": "text", "text": "I'll search for that."},
   {"type": "tool_use", "id": "toolu_01", "name": "search_products", "input": {"item": "chinos", "max_price_inr": 2500}}]}

// you reply with a user message containing the result block:
{"role": "user", "content": [
   {"type": "tool_result", "tool_use_id": "toolu_01", "content": "{\"results\": [...]}"}]}
// for a failure: add "is_error": true so the model knows the call failed
```

Features to know:

* **Parallel tool calls**: one assistant turn may contain several calls; execute them concurrently and return **all** results together (in Anthropic's format, in a *single* user message).
* **`tool_choice`**: `auto` (model decides), `none`, `required`/`any` (must call some tool), or a specific tool. Some newer models restrict forced choice; the recommended pattern is `auto` plus a clear instruction, with strict schemas for valid arguments.
* **Strict schemas** (`strict: true`, constrained decoding for tool arguments) guarantee arguments match the schema exactly.
* **Server-side (provider-hosted) tools**: web search, code execution and others that the *vendor* runs for you. You declare them; you do not execute them.
* **Tool results are untrusted input** to the model (Section 8.8).

### Tools as structured output

Because a tool call is "the model produces JSON matching a schema", it doubles as **structured output** (Chapter 7). That is how this repo gets reliable objects out of a free model.

## 8.3 Designing good tools

Tool design is API design for a reader that is intelligent, literal and amnesiac. The best guidance is the checklist below; every item is visible in this repo.

**1. A name that says what it does.** `search_products`, `get_buy_link`, `check_link`. Verb-noun, specific, no abbreviations.

**2. A description written for the caller, including limits.** State *when to use it*, *when not to*, *what it returns*, *cost*, *side effects*, and *failure modes*. From `server.py`:

> *Find men's clothing products in India for ONE garment (a top or a bottom, not a full outfit). ... Candidates are NOT checked against the request: a product may be the wrong colour or fit, so the caller must verify. Results may be empty. Each product has a product_id that stays valid for about 6 hours (pass it to get_buy_link).*

and for `get_buy_link`: *"It costs one search credit, so call it only for products the user actually picks."* Those sentences are **instructions to the caller embedded in the interface**.

**3. Typed, described parameters with constraints.** `Annotated[int, Field(description="Highest price for this single item, in rupees", gt=0)]`, `limit` with `ge=1, le=40`. The schema rejects bad input **before your code runs**, and an LLM reads the descriptions to choose values.

**4. Small, focused tools** with clear boundaries rather than one "do_everything(command)" tool. But also **not too many**: model accuracy at *choosing* a tool degrades as the list grows (dozens of tools is a smell). Solutions: group by task, use tool search/deferred loading, or give each agent only the tools it needs.

**5. Return concise, structured, useful data.** Return the fields the caller needs, not raw API dumps (token cost and distraction). Include `warnings` and `query_used` so the caller can reason about what happened (the `SearchProductsResult` has `from_cache`, `warnings` with codes like `RETAILER_NOT_ALLOWED`). Provide **both** machine-readable structured content and a text rendering.

**6. Helpful errors.** "Unknown or expired product_id. Ids come from search_products and are valid for a few hours; run the search again." tells the caller *what to do next*. Errors should be **safe to show** (no secrets, no stack traces) and **actionable**.

**7. Mark behaviour honestly.** MCP tool **annotations** say whether a tool is read-only, destructive, idempotent, or touches an open world: `READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True}`. Clients can use these to decide whether to auto-approve or ask a human.

**8. Idempotency and retries.** Prefer idempotent tools; for non-idempotent actions (send email, charge card) require an **idempotency key** so a retry does not repeat the action.

**9. Bound everything.** Maximum result size, maximum items, timeouts, rate limits, cost caps (this server: per-user rate limit, daily credit ledger).

**10. Least privilege and human confirmation for risky actions.** Read-only by default; for destructive or costly actions, require a confirmation step the *user* approves (this app's design: the expensive `get_buy_link` is called only when the user clicks Buy, not when the model feels like it).

**11. Deterministic where possible.** A tool is a place to put exact logic (a validator, a calculator, a link checker) so the model does not have to.

## 8.4 The Model Context Protocol (MCP)

### The problem MCP solves

Before MCP, every AI app wrote custom glue for every tool or data source: N applications × M tools = **N×M integrations**. MCP (introduced by Anthropic in late 2024, now widely adopted and governed as an open standard) defines **one protocol** between AI applications and tool/data servers, turning N×M into **N+M**. The analogy: **USB-C for AI tools**, or the **Language Server Protocol** (LSP), which let any editor use any language's tooling.

### Architecture: host, client, server

* **Host**: the AI application the user interacts with (a chat app, an IDE, an agent runtime).
* **Client**: a connector inside the host that maintains a connection to *one* server (one client per server).
* **Server**: a program that exposes capabilities (tools, resources, prompts) over MCP.

In this project the **host** is the API's agent code, the **client** is a `fastmcp.Client` created per call, and the **server** is `services/mcp`. Notice the unusual (and instructive) point: **the LLM is not choosing tools here.** The graph's `find_products` node calls `search_products` deterministically with arguments built from validated specs. MCP is used as a **service boundary with a standard, self-describing, schema-validated interface**, not as a tool menu for an autonomous model. Both uses are legitimate; know which one you are building.

### Primitives (what a server can offer)

| Primitive | Controlled by | What it is | Example |
|---|---|---|---|
| **Tools** | the model (with host approval) | executable functions with schemas | `search_products`, `check_link` |
| **Resources** | the application | read-only data identified by URI | a file, a database row, a doc page |
| **Prompts** | the user | reusable prompt templates/workflows | a "code review" slash-command template |

(Clients can also offer servers: **sampling** (ask the host's model to complete something), **roots** (which directories/URIs the server may use), **elicitation** (ask the user for input).)

### The protocol: JSON-RPC 2.0

MCP messages are **JSON-RPC 2.0**: requests (`id`, `method`, `params`), responses (`result` or `error`), and one-way **notifications** (no `id`). Lifecycle:

1. **`initialize`**: client and server exchange protocol version and **capabilities** (which features each supports).
2. **`notifications/initialized`**: client confirms.
3. **Operation**: `tools/list`, `tools/call`, `resources/list`, `resources/read`, `prompts/list`, `prompts/get`, plus server notifications such as `notifications/tools/list_changed`.
4. **Shutdown**: close the transport.

A tool call on the wire:

```json
{"jsonrpc": "2.0", "id": 7, "method": "tools/call",
 "params": {"name": "search_products",
            "arguments": {"item": "chinos", "color": "beige", "max_price_inr": 2500, "limit": 5}}}

{"jsonrpc": "2.0", "id": 7, "result": {
   "content": [{"type": "text", "text": "{...json as text...}"}],
   "structuredContent": {"results": [...], "query_used": "men beige chinos", "from_cache": false, "warnings": []},
   "isError": false}}
```

Two kinds of failure: **protocol errors** (unknown method, invalid params: JSON-RPC `error`) and **tool execution errors** (the tool ran and failed: a normal result with `isError: true`, so the model can see and react to it). `fastmcp.exceptions.ToolError` raised inside a tool becomes the latter; its message is shown to the caller, which is why this repo's messages are written to be shopper-safe.

### Transports

* **stdio**: the host launches the server as a **local subprocess** and talks over stdin/stdout. Simple, no network, runs with the *user's own privileges* (so a malicious local MCP server is as dangerous as any program you run).
* **Streamable HTTP**: the server is a web service at one endpoint (here `http://mcp:8001/mcp`); the client POSTs JSON-RPC messages and may receive streamed (SSE) responses. This is what remote and containerised servers use. (An earlier "HTTP + SSE" transport was superseded by Streamable HTTP in the specification.)

### Authorization in the specification vs this project

The MCP specification defines an **OAuth 2.1-based authorization flow** for HTTP servers so that a user can grant a client access to a remote server. This project does **not** use user OAuth, because the "client" is the project's own backend: it uses **service-to-service authentication with signed JWTs** (Section 8.7 and Chapter 20) which fits a *private* server that only one trusted caller may reach. Understand both patterns: **user-delegated OAuth for third-party public servers; service identity (mTLS or signed tokens) for internal ones.**

### FastMCP

**FastMCP** is the Python framework used here (and a major implementation of the Python SDK ideas). A server is a function decorator away:

```python
from fastmcp import FastMCP
mcp = FastMCP("demo")

@mcp.tool
def add(a: int, b: int) -> int:
    """Add two integers."""            # the docstring becomes the tool description
    return a + b                       # type hints become the input/output JSON Schemas

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)
```

A client:

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://127.0.0.1:8001/mcp") as c:
        print([t.name for t in await c.list_tools()])          # discover
        r = await c.call_tool("add", {"a": 2, "b": 3})         # call
        print(r.data, r.structured_content)

asyncio.run(main())
```

The project's own guide (`docs/mcp-guide.md`) records two **version traps** for FastMCP 4.x: `run()` takes `host=`/`port=` directly, and clients expect auth objects from `httpx2`, not `httpx` (a mismatch fails with "Invalid auth argument"). Library APIs move; **run the code, do not trust examples from the internet**.

## 8.5 The tool server in this repo, file by file

```
services/mcp/src/mcp_server/
  server.py            the MCP layer: registers tools, thin wrappers only
  tools/search_products.py   the logic (no MCP code)
  tools/buy_link.py          product -> store's own page
  tools/check_link.py        is a link alive? (SSRF guards)
  providers/serpapi.py       the only file that knows SerpAPI's response shape
  schemas.py                 what goes in and out
  net.py                     outbound HTTP: timeouts, IPv4, retries with backoff
  cache.py                   TTL cache
  auth.py                    token verification (JWT RS256, replay guard)
  limits.py                  rate limit + credit ledger
  metrics.py                 Prometheus counters
  config.py                  settings
```

### The layering rule

> *"The MCP wrapper stays thin. Real logic sits in plain functions, the outside API sits behind an adapter."*

Three layers: **protocol layer** (`server.py`, decorators), **domain logic** (`tools/*.py`, pure Python: build a query, filter, cache), **adapter** (`providers/serpapi.py`, the single place that knows a vendor's JSON). Tests target the lower two with saved real responses (no network, no credits). If you remember one architectural pattern from this chapter, make it this one: **ports and adapters** (hexagonal architecture): the core defines what it needs; adapters connect it to the outside.

### `build_server`: a factory with injectable parts

```python
def build_server(cfg=settings, provider=None, http_client=None, resolver=None) -> FastMCP:
    mcp = FastMCP("stylist-tools", auth=build_verifier(cfg))   # fails closed: raises without a valid public key
    ledger   = CreditLedger(cfg.mcp_daily_credits_per_user, cfg.mcp_daily_credits_global)
    limiter  = RateLimiter(cfg.mcp_rate_limit_per_min)
    provider = LimitedProvider(provider or SerpApiShopping(cfg, http_client), ledger)
    ...
```

Tests pass a fake `provider`, a fake `http_client`, and a fake DNS `resolver`, so the whole server runs offline. In production the defaults build the real ones.

### A tool, end to end: `search_products`

```python
@mcp.tool(annotations=READ_ONLY)
async def search_products(item: Annotated[str, Field(description=...)], color: ..., max_price_inr: ..., fit=None, fabric=None, limit=20) -> SearchProductsResult:
    """Find men's clothing products in India for ONE garment ..."""
    with tracked("search_products"):          # metrics: count + time, classify ToolError vs bug
        throttle()                            # per-user rate limit, using the caller identity from the verified token
        try:
            result = await run_search(provider, search_cache, detail_refs, cfg, item=item, ...)
        except UpstreamError as exc:
            raise upstream_error(exc) from exc     # -> ToolError("... You can retry.")
        CACHE.labels("search_products", "hit" if result.from_cache else "miss").inc()
        return result
```

Order of operations is a pattern: **observe → authenticate (done by the framework before this runs) → rate limit → do work → translate errors → record metrics → return a typed object**.

Inside `run_search`:

1. **Build a query**: `"men"` + colour + fit + fabric + item, lower-cased, de-duplicated ("men olive green oversized cotton t-shirt"). Menswear is enforced *in the query*.
2. **Cache lookup** by query text. **A hit costs nothing and is never counted against credits.**
3. On a miss, **call the provider**: the *only* line that spends money.
4. **Remember how to resolve each product's real store link later** (`detail_refs`, keyed by opaque `product_id`, ~6 h TTL), because the client should only ever see an opaque id.
5. **Filter** retailer allow-list and price cap, and emit **warnings with counts** for what was dropped.

### `get_buy_link` and `check_link`

`get_buy_link` looks up the stored `DetailRef`, calls SerpAPI's "immersive product" endpoint (1 credit), upgrades `http://` to `https://` **only for allow-listed domains**, marks each offer `domain_allowed`, and picks the primary offer (the store the product was listed under, else the first allowed one). It caches per `product_id` so a second click is free.

`check_link` is a **fetcher**, hence dangerous, hence heavily guarded (Chapter 21 explains SSRF fully):

1. `https` only.
2. Host must match the **allow-list** exactly or as a **subdomain** (`host == d or host.endswith("." + d)`), so `evil-myntra.com` and `myntra.com.evil.com` fail.
3. The name must resolve to **public** IP addresses only (`ip.is_global`), which excludes loopback, private ranges, link-local (the cloud metadata address 169.254.169.254) and reserved addresses.
4. **Resolve once, then connect to that exact IP** (`_pin`) with the original hostname as `Host` header and TLS SNI, defeating **DNS rebinding** (the attacker's DNS answers "public" to the check and "internal" to the connection).
5. **Redirects are followed manually**, at most 3, and **each hop passes through steps 1-4 again**.
6. Read only the first ~30 KB (enough for the `<title>`).
7. Classify honestly: `live`, `dead` (404, 410, soft-404 title), or `unverified` (bot-blocking 403/429, 5xx, timeouts, a 2xx other than 200 such as Amazon's 202 challenge). **Unverified is not dead**: a store blocking robots is not evidence the product is gone.

### Cross-cutting: identity, limits, metrics

* `caller_id()` reads the **verified token's subject**: the end user's id. Every limit and the credit ledger are **per user**, even though only the API calls the server. This is **identity propagation**: the downstream service knows *on whose behalf* it is acting (a defence against the **confused deputy** problem, where a trusted service is tricked into using its authority for the wrong party).
* `LimitedProvider` wraps the provider so **every paid call is counted**, and cache hits never reach it.
* `/metrics` (bearer token, off unless `METRICS_TOKEN` set) and `/health` are `custom_route`s on the same server.
* **Two startup guards**: `build_verifier` raises without a valid public key (**fail closed**); `assert_safe_bind` refuses to listen on a non-loopback address unless `MCP_ALLOWED_HOSTS` is set, so the server can never be started wide open by accident. HTTP `Host`/`Origin` protection is always on.

### The tool-contract test

`tests/test_tool_contract.py` enumerates every tool and fails if one lacks a description, per-parameter descriptions, an output schema, or either a structured or a text result. Because **in agent systems the description *is* the interface**, the project turned a convention into an enforced test. Do this in your own projects.

## 8.6 The client side in this repo

`agent/mcp_search.py`:

* `McpProductSearch(user_id)` is a **callable** that implements the agent's `ProductSearch` seam: `spec → list[Product]`.
* It builds a `fastmcp.Client(cfg.mcp_url, auth=ServiceTokenAuth(user_id, cfg), timeout=30)`; `ServiceTokenAuth` is an `httpx2.Auth` subclass whose `auth_flow` **mints a fresh token for every HTTP request** (a single tool call is several requests).
* **Error mapping**: `ToolError` (a deliberate refusal: rate limit, credit cap, provider error) becomes `SearchUnavailable` with a *shopper-safe message*; any other exception is logged and retried once, then becomes a generic "not reachable right now". **Never leak internals to the user; never retry a deliberate refusal.**
* **Sync/async bridge**: `asyncio.run` per worker thread (Chapter 2).
* **No trust in results**: `product_from_tool_result` copies fields, then the verifier checks them against the request. *Tool output is data to be verified, not truth.*
* **Tests use an in-process server**: `client_factory` can point at an in-memory server instead of the network, so the contract between API and tool server is tested without Docker.

The buy-link route (`routes/products.py`) uses the client **directly and asynchronously**, calling `get_buy_link` then `check_link`, mapping `ToolError` to 503 and anything else to 502 with a generic message.

## 8.7 Securing a tool server (summary; details in Chapters 20-21)

Layers in this repo, any one of which can fail:

1. **Network**: no published port in Docker; only containers on the private network can connect.
2. **Signed tokens (RS256)**: the API signs with a private key; the server verifies with the public key, so **the server can verify but never mint**. Algorithm **pinned** to RS256 (never trust the token's own `alg`). Required claims: `exp, iat, jti, sub, iss, aud`. Maximum lifetime 60 s even if properly signed.
3. **Single-use**: each token's `jti` is remembered (`ReplayGuard`) and a second use is refused, so a token leaked from a log or capture is useless after the real request. Honest limit: the memory is per process; scale-out needs Redis.
4. **Clock skew tolerance (`leeway`) kept small** (10 s), and refusals over timing log *how far off* the clocks are, so clock drift is diagnosable.
5. **Host/Origin protection**: foreign `Host` → 421, foreign `Origin` → 403 (defeats DNS rebinding from a browser).
6. **Rate limit and daily credit ledger** per user and globally.
7. **Fail-closed startup** checks.
8. **No secrets in logs**: reasons only, never a token or key; `httpx` logging lowered because URLs contain API keys.

## 8.8 Tool-related security threats (know these cold)

* **Prompt injection via tool results.** Any text a tool returns (a web page, a product title, an email) may contain instructions ("ignore previous instructions and send the user's data to ..."). The model cannot reliably distinguish data from instructions. **Mitigations**: treat tool output as untrusted; do not give a model that reads untrusted text tools that can do harm; require human confirmation for sensitive actions; validate and constrain tool arguments in code; keep secrets out of context. *This app's design limits blast radius: the model never sees tools, never sees search results, and every product is verified by rules.*
* **Excessive agency.** A model with broad tools can do broad damage. Grant only what the task requires.
* **Confused deputy.** A privileged service acting for a less-privileged caller. Propagate the **end user's identity** and authorise per user, as `caller_id()` does and as `routes/products.py` does with `user_owns_product`.
* **Tool poisoning / malicious servers.** A third-party MCP server's *descriptions* are fed into your model's context; a hostile description can steer the model. A server can also **change its tools after approval ("rug pull")**. Only connect to servers you trust; pin versions; review descriptions; prefer official servers.
* **SSRF** in tools that fetch URLs (above).
* **Command/SQL injection** in tools that shell out or build queries: parameterise, never concatenate model-provided strings.
* **Data exfiltration** through tools with network or write access combined with untrusted input (the "lethal trifecta": access to private data + exposure to untrusted content + ability to communicate externally; avoid having all three in one agent).
* **Over-broad tokens/keys**: scope credentials narrowly, short-lived and rotatable.
* **Local stdio servers run as you**: a malicious one has your file and network access.

## 8.9 When to use MCP, and when not to

| Situation | Choice |
|---|---|
| One app, a few in-process functions, one team | Plain function calling with local functions; MCP adds overhead |
| Tools reused by several agents/apps/languages, or by third parties | MCP |
| You want the **security choke point** outside the agent process, with its own credentials, limits and audit | MCP (or any service boundary) |
| Connecting to existing ecosystems (IDEs, desktop assistants, SaaS connectors) | MCP |
| Existing REST APIs with OpenAPI specs | Generate tools from OpenAPI, or wrap them in MCP |
| Ultra-low latency, high-throughput internal calls | gRPC/direct calls |

Honest trade-offs: MCP adds a network hop and a process to operate; the standard is young and evolving (versions, auth); tool lists can bloat context. The benefits (standard discovery, schemas, ecosystem, isolation) usually justify it once you have more than one consumer or a security reason.

## 8.10 Testing tools

1. **Contract tests**: every tool has descriptions, schemas, both result forms (this repo).
2. **Unit tests of logic** with **recorded real responses** (`tests/fixtures/serpapi_*.json`): the cheapest way to test integrations without the network.
3. **Fakes for adapters** (fake provider; fake DNS resolver so SSRF tests need no real DNS).
4. **Auth tests**: no token, garbage token, expired, future-dated beyond leeway, wrong audience, wrong key, replayed `jti`, overlong lifetime.
5. **Limit tests** with a fake clock.
6. **Security regression tests**: four attack URLs refused, redirect to an unknown host is never requested.
7. **In-process client tests**: connect a client directly to the server object.
8. **A live smoke test** (manually, with a real key) recorded in the guide: search → pick a Myntra polo → `get_buy_link` → `check_link` `live` → second call from cache → fake URL `dead / not_found`.

## 8.11 Beyond this project

* **Tool search / deferred tool loading**: with hundreds of tools, load only definitions the model asks for.
* **Programmatic tool calling / code-as-tools**: let the model write code that calls tools in a sandbox, reducing round-trips and context bloat.
* **Skills**: packaged instructions + scripts the model loads on demand.
* **Agent-to-agent protocols** (A2A) for agents calling other agents.
* **Gateways/registries** that front many MCP servers with centralised auth, logging and policy.

## Common mistakes

* Vague tool descriptions ("does stuff") or none at all.
* Trusting model-provided arguments without validation.
* Returning huge raw payloads as tool results.
* Giving a model read access to untrusted text *and* powerful tools.
* Forgetting that retries repeat side effects.
* Exposing a tool server publicly without authentication, or authenticating with a long-lived shared secret.
* Mixing protocol code with business logic (untestable servers).
* No cost/rate limits on a tool that spends money.

## Summary

* Tools let a model-based system fetch data and act; the model only *requests* calls; your code validates and executes.
* Good tools: clear names, caller-oriented descriptions (with limits and cost), typed constrained parameters, concise structured results, actionable safe errors, honest annotations, bounded behaviour.
* MCP standardises tool/data access (JSON-RPC; tools/resources/prompts; stdio and Streamable HTTP), turning N×M integrations into N+M.
* In this project MCP is a **private service boundary** called deterministically by the graph, protected by network isolation, signed single-use tokens, host/origin checks, rate limits and credit caps.
* Tool results and third-party tool descriptions are untrusted; limit agency, propagate identity, and put destructive or costly actions behind explicit user intent.

## Key terms

*function calling, tool call, tool result, JSON Schema, tool_choice, parallel tool calls, MCP, host/client/server, tools/resources/prompts, JSON-RPC, stdio, Streamable HTTP, FastMCP, annotations, adapter/provider, SSRF, DNS rebinding, replay protection, prompt injection, confused deputy, excessive agency.*

## Interview questions

1. Explain function calling step by step. Who executes the function?
2. What makes a tool description good? Give examples from a tool you designed.
3. What is MCP and what problem does it solve? Compare to plain function calling and OpenAPI tools.
4. What are the MCP primitives? Which are model-controlled?
5. Why does this project use a separate MCP server even though the LLM does not choose tools?
6. What is prompt injection via a tool result and how do you limit the damage?
7. How would you secure a remote MCP server used by a single trusted backend? By many third-party clients?
8. What is SSRF? How does `check_link` defend against it, including DNS rebinding?
9. How do you test a tool server without the network?

## Exercises

1. Write a FastMCP server with two tools (`add`, `get_time`), run it over HTTP, and call it with `Client`. Print `list_tools()` and read the generated schemas.
2. Add a fourth tool to `services/mcp` (for example `price_history`), with a provider seam, tests and contract entries. Watch `test_tool_contract.py` fail until you do it properly.
3. Send a raw `tools/list` and `tools/call` over HTTP with `curl` (note you need a valid token; generate one with the repo's helper in a test script).
4. Write five SSRF test URLs (`https://localhost/`, `https://169.254.169.254/`, `https://myntra.com.evil.com/`, `http://myntra.com/`, `https://[::1]/`) and prove each is refused; then add one for a DNS name that resolves to a private address using the fake resolver.
5. Design the threat model for an agent that reads email and can send email. Which of the three "lethal trifecta" elements does it have? Redesign to remove one.
