# MCP server: plan and step-by-step guide

Written for someone building their first MCP server. Each step says what to learn, what to run,
and how to know it worked. Steps 1-3 are built and tested; the rest are planned.

## 1. The idea in five minutes

**The problem.** Your agent (LangGraph) needs abilities outside the language model: search for
products, check a link, generate an image. You could call those as plain Python functions. MCP
(Model Context Protocol) is a standard way to put them behind a small server instead.

**The picture.**

```
 LangGraph agent ──(MCP client)──►  MCP server  ──►  SerpAPI, retailers, image model
 Mastra gateway  ──(MCP client)──►  (your tools)
```

- **Server**: lists the tools it offers and runs them when asked.
- **Client**: connects, asks "what tools do you have?", then calls one by name with arguments.
- **Tool**: a function with a name, a description, a typed input schema and a typed output schema.
- **Schema**: the contract. The client reads it automatically, so nobody guesses what a tool wants.
- **Transport**: how they talk. We use HTTP at `http://127.0.0.1:8001/mcp`.

**Why bother, for this project?**
1. One place for tools, shared by LangGraph and Mastra (no duplicated code).
2. The schema validates every call before your code runs.
3. One choke point for security (login token check, rate limits, audit log) in phase 4.
4. Swap SerpAPI for another provider without touching the agent.

**Three call types you will see:** `list_tools` (what do you offer?), `call_tool` (run it),
and a result that is either data or a clean error.

## 2. Where the code lives

```
services/mcp/src/mcp_server/
  server.py              the MCP layer: registers tools, thin wrappers only
  tools/search_products.py   the logic (no MCP code, so it is easy to test)
  tools/buy_link.py      resolves a product to the store's own page
  tools/check_link.py    is a link alive? includes the safety guards
  providers/serpapi.py   the only file that knows SerpAPI's response shape
  schemas.py             what goes in and out of the tools
  net.py                 outbound HTTP: timeouts, IPv4, retries with backoff
  cache.py               a small in-memory cache with an expiry time
  auth.py                who may call the server (the agent's secret token)
  config.py              settings from the repo-root .env
services/mcp/tests/      67 tests, using real saved SerpAPI responses
```

**The rule behind that layout:** the MCP wrapper stays thin. Real logic sits in plain functions,
the outside API sits behind an adapter. That is why the tests need no network and no credits.

## Step 1 - Run a server and talk to it  (done)

**Learn:** the discover-then-call loop.

```bash
cd services/mcp
uv run python -m mcp_server.server        # leave this running in one terminal
```

In a second terminal, save this as `try_client.py` and run `uv run python try_client.py`:

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("http://127.0.0.1:8001/mcp") as c:
        tools = await c.list_tools()
        print([t.name for t in tools])               # ['ping', 'search_products']
        print((await c.call_tool("ping", {})).data)  # pong
asyncio.run(main())
```

**It worked if:** you see both tool names and `pong`. The server terminal logs `POST /mcp ... 200`.

**Things I found while building (FastMCP 4.0.10):** `run()` takes `host=` and `port=` directly;
the old `Tool.inputSchema` is now `input_schema`. Version differences like this are why you run
things instead of trusting examples from the internet.

## Step 2 - Build the first real tool: `search_products`  (done)

**Learn:** schemas, layers, caching, retries, tests.

Read the files in this order:
1. `schemas.py` - what a product looks like. Notice `url_kind`: SerpAPI search results do **not**
   give the store's own link, only a Google Shopping page, and the field says so honestly.
2. `providers/serpapi.py` - `parse_shopping_results` turns raw JSON into typed products.
3. `net.py` - `get_json` retries a 429/5xx with growing waits, but fails at once on a bad key.
4. `tools/search_products.py` - builds the query ("men" + colour + fit + item), checks the cache,
   calls the provider, drops stores we do not show and items above the price cap.
5. `server.py` - the `@mcp.tool` wrapper. The docstring and `Field(description=...)` are what a
   client (or a model) reads, so write them for that reader.

**Try it:** with the server running, call it:

```python
r = await c.call_tool("search_products",
        {"item": "chinos", "color": "beige", "max_price_inr": 2500, "limit": 5})
print(r.structured_content["results"][0])
```

Run it twice. The second call has `from_cache: true` and spends no credit.
(First live call took 0.79 s; the cached one 0.01 s.)

**Run the tests:** `cd services/mcp && uv run pytest -q` -> 13 passed.

**Exercises (to make it stick):**
- Change `limit` to 100. What happens, and who rejected it? (the schema, before your code)
- Add a retailer to `DEFAULT_ALLOWED_RETAILERS` and see a warning count drop.
- Write a test for a query with fit and fabric.

**Security note:** the server listens on `127.0.0.1` (this machine only) on purpose, and since
the "Only the agent" step below it also demands a secret token on every call.

## Step 3 - Add `get_buy_link` and `check_link`  (done)

**Learn:** a second tool that depends on the first, and why a tool that fetches URLs must be guarded.

`get_buy_link(product_id)` turns a search result into the store's own page (and stock). Search
results only link to a Google Shopping page, so this costs 1 credit and should be called only
when the user picks a product. How it works: when `search_products` runs, the server remembers
(in memory) how to look each product up and hands the client only the opaque `product_id`. The id
lives about 6 hours; after that the tool says "expired, search again".
Files: `tools/buy_link.py`, plus `parse_offers` and `SerpApiShopping.offers` in `providers/serpapi.py`.

`check_link(url)` says whether a link is `live`, `dead` or `unverified` ("we could not tell",
e.g. the store blocks automated checks, which is NOT the same as broken). File: `tools/check_link.py`.
Its guards, in order, applied again on every redirect hop:
1. https only  2. host must be on the allow-list (matched exactly or as a subdomain, so
`evil-myntra.com` and `myntra.com.evil.com` fail)  3. the host must resolve to public internet
addresses only (no 127.x, 10.x, 192.168.x, 169.254.169.254 cloud-metadata...). This is called SSRF
protection: without it, a tool that fetches URLs can be tricked into reading your own machine.
Known limit (written in the file): the address could change between our lookup and the connection
(DNS rebinding). Fix this before exposing the server beyond localhost.

Also added: every tool is marked read-only (safe to retry), and `tests/test_tool_contract.py`
checks that **every** tool has a description, per-input descriptions, an output schema, and returns
both a structured and a text result. If you add a tool, that test fails until you list it.

**Run the tests:** `cd services/mcp && uv run pytest -q` -> 67 passed.

**Live run (real SerpAPI, real Myntra):**
search -> picked a Myntra polo -> `get_buy_link` returned the Myntra page (https, in stock, Rs 1429)
-> `check_link` said `live` (HTTP 200) -> a second `get_buy_link` came from cache -> a made-up
Myntra URL came back `dead / not_found (404)`. Four attack URLs were refused.

**Exercises:**
- Add a store to `DEFAULT_ALLOWED_DOMAINS` and confirm `check_link` now accepts it.
- Write a test where a store returns 403 and see why the verdict is `unverified`, not `dead`.
- In `tests/test_check_link.py`, find the test that proves a redirect to an unknown host is
  never requested, and explain why that matters.

## Step 4 - Make LangGraph call the server

**Learn:** the client side, and why contracts matter.

Replace `mock_search` with a function that calls `search_products` over MCP (through
`langchain-mcp-adapters` or the FastMCP `Client`), mapping each result to the agent's `Product`.
The graph does not change, because `ProductSearch` is already the seam.
**It worked if:** the real conversation test returns outfits built from real products, and the
verifier still rejects wrong-colour items.

Also here: free page lookups (Myntra pages state colour, gender and stock) to turn "assumed
colour" into "confirmed". That belongs in the agent's enrichment step, not in the search tool.

## Step 5 - Image tools

`generate_image`, `create_character_sheet`, `generate_tryon`, `get_job`, as designed in
`docs/tools-reference.html`. **Blocked** until the image provider is chosen: I could not verify
the model name from your notes, nor whether OpenCode or OpenRouter serves image models.
Everything provider-specific stays in one adapter, like `providers/serpapi.py`.

## Only the agent may call it  (done, between steps 3 and 4)

Requirement: the MCP server must not be usable on its own, only through the agent. Layers:
1. **Network:** it listens on `127.0.0.1` only (`MCP_HOST`). In production it gets a private
   address with no public URL.
2. **A signed, short-lived, single-use token on every request** (JWT, RS256; `auth.py` on the MCP
   side, `api/mcp_auth.py` on the API side). The API signs with a PRIVATE key; the MCP server
   verifies with the matching PUBLIC key and can never create a token. Without a valid token the
   server answers 401 before any tool code runs. It **refuses to start** without a valid public key.
3. **Host/Origin check:** a foreign `Host` (421) or `Origin` (403) is refused even with a valid
   token, which stops a web page in your browser from reaching a local server (DNS rebinding).

Create the key pair once: `uv run --project services/mcp python scripts/generate_jwt_keys.py`.
Private key = API service only. Public key = MCP service only. Re-running rotates both.

**Two weaknesses of short-lived tokens, and the fixes**
- *Clocks disagree.* Two machines are never exactly in step; a token stamped 8 s in the future
  would look "not valid yet". The server allows a small fixed leeway (`MCP_JWT_LEEWAY_S`, default
  10 s) and no more, because leeway also lengthens a token's life. A refusal over timing is logged
  with how many seconds off it was (`iat +24s ... vs our clock`), so clock trouble is visible.
  Also: a correctly signed token claiming to live longer than 60 s is refused.
- *A stolen token works until it expires.* So each token has a unique id (`jti`) and the server
  accepts each id **once**. A copy taken from a log or a network trace is useless after the real
  request has used it. For this to work the API mints a **new token for every HTTP request**
  (one tool call is several requests), each living only 30 s. Limit: the memory of used ids is in
  the server's own memory, so before running several copies of the server it must move to a shared
  store such as Redis.

**Proven against the real running server** (API-side signer, MCP-side verifier, over HTTP): the
agent session works with a fresh token per request; no token or a garbage token -> 401; the same
token used twice -> 200 then 401; API clock 8 s ahead -> accepted, 25 s ahead -> 401; foreign Host
-> 421; foreign Origin -> 403. The server log holds reasons only, never a token or a key.

**Version trap (FastMCP 4):** its client expects auth objects from the `httpx2` package, not
`httpx`. A signer built on the wrong one fails with "Invalid auth argument".

## Step 6 - Rest of the security work (phase 4)

The JWT login itself is now done (above). Still to do: per-user rate limits and a daily credit cap
using the user id in the token, the hash-chained audit log, and the user login for the web app.

## Step 7 - Let Mastra use the tools too

Mastra's MCP client points at the same URL. Then deploy both services (phase 7).

## Differences from `docs/tools-reference.html`

The reference doc was written before building. What changed in the real tool:
- `search_products` has no `category` input (the item name already says top or bottom) and no
  `retailers` / `exclude_urls` / `deadline_ms` yet.
- Results carry `product_id`, `url_kind`, `rating`, `reviews`, `delivery`, and no `in_stock` or
  colour fields (the search data does not provide them).
- A price cap and the retailer allow-list are applied as cheap pre-filters; the agent's verifier
  still makes the real match decision.

## Glossary

- **MCP**: protocol for exposing tools to AI apps. **FastMCP**: the Python library we use.
- **Schema**: the machine-readable description of a tool's inputs and outputs.
- **Adapter/provider**: code that hides one outside service behind a simple function.
- **TTL cache**: remembers an answer for a fixed time. **Backoff**: waiting longer after each retry.
- **SSRF**: tricking a server into requesting internal addresses. **Idempotent**: safe to repeat.
