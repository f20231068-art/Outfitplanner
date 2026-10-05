# Chapter 2. Programming Mental Models

> **Learning objectives.** Build an accurate mental model of how programs run: values and references, types, functions and closures, generators, exceptions, concurrency (threads, async, locks), resource management, configuration, and dependency management. Recognise each idea in this repo's Python and TypeScript.
>
> **Prerequisites.** You have written some Python or JavaScript. Nothing else.

Before data structures and algorithms (Chapters 3-4) you need a trustworthy picture of *what the machine is doing when your code runs*. Most "mysterious" bugs (a list that changed by itself, a request that hangs, a race condition) are failures of this picture, not of the language.

---

## 2.1 How a program runs

### Source, interpreter, process

You write **source code**. Python is run by an **interpreter** (CPython compiles your code to *bytecode* and a virtual machine executes it). TypeScript is compiled (transpiled) to JavaScript, which an engine (V8 in Node and Chrome) runs. When you start it, the operating system creates a **process**: an isolated running instance with its own memory, file handles and at least one **thread** of execution.

A **thread** is a sequence of instructions the CPU runs. A process can have many. Threads in one process **share memory**, which is powerful and dangerous (Section 2.7). Processes do **not** share memory unless they ask the OS to.

In this project every container is one or more processes: `uvicorn` (the API), `python -m mcp_server.server`, `next start`, `caddy`, `postgres`. When Docker says "stop the container", it signals the main process to exit.

### Memory: the stack and the heap

Two regions matter:

* The **stack** holds *function calls*: each call gets a frame with its local variables and where to return. Frames are created and destroyed in strict last-in-first-out order. A function that calls itself forever fills the stack (a *stack overflow*, `RecursionError` in Python).
* The **heap** holds *objects* that can outlive a single call: lists, dictionaries, class instances, strings. Variables on the stack hold **references** (pointers) to them.

Python and JavaScript manage the heap for you with **garbage collection**: when no variable can reach an object any more, its memory is reclaimed. You do not free memory manually, but you *can* leak it by keeping references you no longer need (a cache that never forgets, a global list that only grows). Look at `services/mcp/src/mcp_server/cache.py`: `TTLCache` has `max_items` and drops the oldest entry when full, precisely so memory cannot grow without bound. `ReplayGuard` in `auth.py` has `MAX_REMEMBERED = 100_000` for the same reason. **Any in-memory structure fed by outside input needs a bound.** That is a security rule too: an attacker who can grow your memory without limit can crash you (denial of service).

### Values and references (the single most important idea here)

In Python, *variables are names bound to objects*. Assignment never copies an object; it binds another name to the same object.

```python
a = [1, 2, 3]
b = a          # b is the SAME list
b.append(4)
print(a)       # [1, 2, 3, 4]  <- a changed, because a and b are one object
```

Objects are **mutable** (lists, dicts, sets, most class instances) or **immutable** (numbers, strings, tuples, frozen dataclasses). Mutating a shared mutable object changes it for everyone holding a reference.

**Shallow vs deep copy.** `dict(x)` or `x.copy()` makes a *new outer container* but its values are the *same* objects. Nested structures need `copy.deepcopy`, or you must avoid mutating them.

**In this project.** `gather_prefs` in `agent/graph.py` writes:

```python
prefs = dict(state.get("prefs") or {})        # a NEW dict: we will modify it
prefs.update({k: v for k, v in extracted.model_dump().items() if v is not None})
return {"prefs": prefs, "missing": [...]}
```

The author copies before modifying so the node does not mutate the *previous* state object in place. LangGraph's design assumes **nodes return changes; they do not edit state**. Mutating state in place is a classic source of "the checkpoint and the live state disagree" bugs. Likewise `clamp_to_budget` uses `spec.model_copy(update={...})` (Pydantic's way to make a modified *copy*) instead of editing the spec.

**The mutable default argument trap** (a favourite interview question):

```python
def add(item, bucket=[]):     # the list is created ONCE, when the function is defined
    bucket.append(item)
    return bucket
add(1); add(2)                # [1, 2]  <- shared between calls!
```

The fix is `bucket=None` and `bucket = bucket or []` inside, or `field(default_factory=list)` in dataclasses and `Field(default_factory=list)` in Pydantic, which this repo uses (`warnings: list[ToolWarning] = Field(default_factory=list)`).

In JavaScript the same idea holds: objects and arrays are references; `const` prevents *rebinding the name*, not mutating the object.

### Identity vs equality

`==` asks "are these equal in value?"; `is` asks "are they the very same object?". Use `is` only for singletons (`None`). In JS prefer `===` (no type coercion).

## 2.2 Types

A **type** is a promise about what operations a value supports. Languages differ on *when* they check:

* **Dynamic typing** (Python, JavaScript): checked when the line runs. Flexible; bugs appear late.
* **Static typing** (TypeScript, Java, Go, Rust): checked before running. Bugs appear early; more ceremony.
* **Gradual typing** (Python with type hints + mypy/pyright; TypeScript): you add types where they pay off.

Python's type hints are **not enforced at runtime** by the interpreter. They are enforced by tools (a type checker) or by libraries that *read* them. **Pydantic** and **FastAPI** read the hints and *do* enforce them at runtime, **at the boundary of your system**, where untrusted data enters. This is the central idea:

> **Validate at the boundary, trust inside.** Outside data (HTTP bodies, LLM output, search results) is parsed into typed objects once, at the edge. After that the code can rely on the types.

### The type tools you will meet in this repo

* **Primitive types and generics**: `int`, `str`, `list[str]`, `dict[str, int]`.
* **Optional / union**: `str | None` means "a string or nothing". Handling `None` explicitly is how you avoid the "billion-dollar mistake" (null reference errors). `budget_inr: int | None = None` in `PrefsExtraction` literally means "not stated yet".
* **`Literal`**: a value restricted to specific constants, e.g. `Category = Literal["top", "bottom"]`, or the verdict `Literal["live", "dead", "unverified"]`. The schema rejects anything else, and a model asked to produce this type is *constrained* to the set.
* **`TypedDict`**: a dict with known keys: `StylistState` in `agent/state.py` (`total=False` makes every key optional). It is just a dict at runtime, with hints for tools.
* **`dataclass`**: a plain class with auto-generated `__init__`, `__repr__`, equality: `Identity(user_id)` (frozen = immutable), `RunStats`, `ChainReport`.
* **Pydantic `BaseModel`**: a class that **validates and converts** input on construction, produces JSON schemas, serialises with `.model_dump()`. `Product`, `Outfit`, `MatchReport`, `ToolWarning`, request bodies like `Credentials` and `MessageIn`.

```python
class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")   # unknown fields are an ERROR, not silently ignored
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
```

Why `extra="forbid"`? If a client sends `{"email": ..., "password": ..., "is_admin": true}`, an API that silently accepts extra fields invites **mass-assignment** bugs. Forbidding makes the contract exact. Why `max_length=128` on the password? To stop someone sending a megabyte "password" to burn CPU in the hashing function.

* **Validators** transform or reject: `PrefsExtraction._blank_means_not_stated` converts the *strings* "None", "null", "unknown" (which some models write instead of a real null) into `None`; `_parse_amount` accepts `"4k"`, `"Rs 4,000"`, `"₹4000"`. This is **defensive parsing of LLM output**: the model's text is an *untrusted input*.

### TypeScript's twist: structural typing and discriminated unions

TypeScript types are **structural**: a value fits a type if it has the right shape, regardless of declared class. In `apps/web/lib/types.ts` the stream events are a **discriminated union**: each variant carries a literal `event` field.

```ts
type StreamEvent =
  | { event: 'status'; data: { stage: string; label: string } }
  | { event: 'outfits'; data: { outfits: Outfit[] } }
  | { event: 'error'; data: { message: string } } /* ... */

if (ev.event === 'status') ev.data.label   // the compiler narrows `ev.data` to the status shape
```

Checking the tag lets the compiler **narrow** the type inside each branch (see `Chat.tsx`'s `for await` loop). The Python analogue is `Literal` tags plus `match`/`if`.

* `unknown` is the safe "I don't know the type yet" (you must check before use); `any` switches the checker off. Prefer `unknown` at boundaries (`JSON.parse` returns `any`, so `parseBlock` in `sse.ts` casts deliberately in one place).
* Types **vanish at runtime** in TypeScript. The compiler cannot validate a server response; libraries like `zod` (used in the Mastra app: `caseSchema = z.object({...})`) do that at runtime.

## 2.3 Functions, closures and decorators

### First-class functions

Functions are values: you can store them, pass them, return them. This repo relies on it constantly:

* `create_app(cfg, pool, graph_factory, tool_client_factory)` takes **factories** (functions that create things) so tests can pass fakes. `app.state.graph_factory = make_graph_factory(llm, search_for_user, saver)`.
* `ProductSearch = Callable[[ItemSpec], list[Product]]` is a *type alias for a function signature*: the agent only needs "something callable that takes a spec and returns products", so it accepts `mock_search` (a function), `McpProductSearch(user_id)` (an object with `__call__`), or `InstrumentedSearch(...)` (a wrapper). This is the **seam** pattern from Chapter 1.

### Closures

A **closure** is a function that *remembers variables from the scope where it was created*. `make_graph_factory` returns an inner `factory` function that remembers `llm`, `search_for_user` and `saver`:

```python
def make_graph_factory(llm, search_for_user, saver):
    def factory(user_id, stats=None):
        stats = stats or RunStats()
        return build_graph(InstrumentedLLM(llm, stats), InstrumentedSearch(search_for_user(user_id), stats), saver)
    return factory
```

`build_graph` itself defines all node functions as *inner functions* that close over `llm` and `search`. That is why the nodes need no global variables: the graph is built per request with *that request's* user-scoped search and stats counters.

JavaScript closures also power React hooks (Chapter 19) and the `refreshing` variable in `api.ts`.

### Decorators

A **decorator** wraps a function to add behaviour, written `@something` above a function. It is just `f = something(f)`. You use them constantly:

* `@app.get("/health")` registers the function as a route.
* `@mcp.tool(annotations=READ_ONLY)` registers a function as an MCP tool and *derives its schema from the type hints and docstring*.
* `@contextmanager` (in `metrics.py`'s `tracked`) turns a generator into something usable with `with`.
* `@field_validator("budget_inr", mode="before")` on a Pydantic model.

Know how to write one: a function that takes a function and returns a new function that calls the original plus extra work (timing, logging, retry).

### Pure functions vs side effects

A **pure function** returns the same output for the same input and changes nothing else. `verify_product(product, spec)` is pure: it reads two objects and returns a report. That is why it has 27 fast tests and no mocks. A **side effect** is anything else: writing to a database, a network call, printing, mutating an argument.

**Functional core, imperative shell**: put decisions in pure functions; push I/O to the edges. The repo does this deliberately: `tools/search_products.py` ("No MCP code in here, so it is easy to test"), `verify.py`, `find.py` are pure-ish logic; `server.py` and `routes/*.py` are the shell.

## 2.4 Iterators, generators and streaming

### Iteration protocol

A `for` loop works on anything **iterable**. Under the hood it calls `iter()` to get an **iterator** and `next()` repeatedly until `StopIteration`.

### Generators: lazy sequences with `yield`

A function containing `yield` returns a **generator**: calling it does *not* run the body; each `next()` runs until the next `yield`, then **pauses**, keeping its local variables. This gives *lazy evaluation* (compute on demand, constant memory) and, crucially for us, **streaming**.

The chat endpoint's inner `events()` function is a generator:

```python
def events():
    ...
    for update in graph.stream(payload, config, stream_mode="updates"):
        ...
        yield sse("status", {...})      # sent to the browser NOW, before the graph finishes
    ...
    yield sse("done", {...})

return StreamingResponse(events(), media_type="text/event-stream", ...)
```

Starlette pulls items from the generator and writes each to the network as it appears. The user sees "Understood your request" while the model is still working on the next step. **Streaming responses are how AI products feel fast** even when the total work takes 30 seconds (Chapter 14).

Note the `finally:` block in `events()`: a generator can be **closed early** (the browser disconnects), and `finally` still runs, so the conversation is released from the "busy" set. Code that must run no matter what belongs in `finally` or a `with` block.

### Async generators in TypeScript

`apps/web/lib/api.ts` has `export async function* sendMessage(...)` and `lib/sse.ts` has `async function* readEvents(body)`. `async function*` combines both ideas: it **awaits** (waits for network data) and **yields** (hands one parsed event to the caller). The consumer writes `for await (const ev of sendMessage(...))`. `yield*` delegates to another generator.

The SSE parser illustrates a **buffering** idiom you will use whenever you parse a stream: network chunks do not align with messages, so you accumulate into a buffer and only act on *complete* units (here, text blocks ending in a blank line `\n\n`), keeping the remainder:

```ts
buffer += decoder.decode(value, { stream: true })
while ((end = buffer.indexOf('\n\n')) !== -1) { /* parse buffer.slice(0, end); buffer = buffer.slice(end + 2) */ }
```

`TextDecoder(..., {stream: true})` matters: a multi-byte character (like ₹, 3 bytes in UTF-8) can be split across chunks, and `stream: true` tells the decoder to wait for the rest.

## 2.5 Errors and exceptions

### Mechanics

`raise` stops normal flow and unwinds the stack until some `except` (catch) handles it. `finally` always runs. Python 3.11+ also has exception groups, rarely needed here.

**Chaining.** `raise HTTPException(...) from exc` records the original cause; `from None` *hides* it deliberately (used in `deps.current_user` so a 401 reveals nothing about why a token failed).

### Principles worth internalising

1. **Fail fast and loud on programmer errors; fail gracefully on user and environment errors.** `assert_safe_bind` raises at startup if the config would expose the server; that is a *deployment mistake*, caught immediately. A search outage during a user's conversation becomes a friendly message, not a crash.
2. **Catch the narrowest exception you can handle.** `except (ValidationError, OutputParserException)` in `structured()` retries only when the model's output was malformed; a network error propagates.
3. **Never swallow silently.** If you must ignore an error, log it. The audit exporter wraps `append` in try/catch and **logs** the failure: "an audit failure must never break the traced request, but it must not be silent either."
4. **Separate the internal error from the user-facing message.** `_friendly(exc)` maps exceptions to safe text; the real exception is logged with `log.exception`. Never leak stack traces, SQL, file paths or keys to users. `main.py` registers a catch-all handler returning "Something went wrong on our side." with status 500.
5. **Use the type system to make failure explicit.** `accounts.rotate` returns a `Rotation(status="ok" | "invalid" | "reuse")` instead of raising for the theft case, because the caller *must still commit* the revocation to the database. Docstring: "Failure cases that must still be saved are returned as a status, never raised, so the caller commits them." This is a deep point: **exceptions roll back transactions; some failures must not.**
6. **Retries need discipline.** Retry only transient failures (timeouts, 429, 5xx), with exponential backoff and jitter, with a limit, on idempotent operations. `net.get_json` does exactly this and fails *immediately* on a 4xx (a bad key will not fix itself). `McpProductSearch` retries a network blip once but never a deliberate `ToolError`.

TypeScript note: `try { ... } catch (err)` types `err` as `unknown`; narrow it (`err instanceof ApiError`). Promises reject; an un-awaited rejected promise is an "unhandled rejection".

## 2.6 Concurrency

This is the topic where interview answers separate juniors from seniors. Build it carefully.

### Two kinds of "slow"

* **CPU-bound** work keeps the processor busy (hashing a password, training a model, resizing an image).
* **I/O-bound** work *waits* for something outside the CPU (a network call to the LLM, a database query, reading a file).

An AI application is overwhelmingly **I/O-bound**: it spends most of its life waiting for a model or a search API. That decides everything about its concurrency design.

### Processes, threads, and the GIL

* **Processes**: isolated memory; true parallelism on multiple cores; expensive to start; communicate via pipes/sockets.
* **Threads**: share memory; cheap; but in **CPython** the **Global Interpreter Lock (GIL)** lets only *one thread execute Python bytecode at a time* (in the standard build). Threads still help I/O-bound work because the lock is released while waiting on I/O. They do not speed up pure-Python CPU work. (Experimental free-threaded builds exist in newer Python versions; the mainstream deployment is still the standard build, and the concepts below hold either way.)

**In this project.** `find_products_for_specs` (`agent/find.py`) runs the eight product searches in parallel:

```python
with ThreadPoolExecutor(max_workers=8) as pool:
    results = list(pool.map(safe_search, items))
```

Eight network calls overlap, so total time is about the *slowest one*, not the sum. This is a textbook use of threads for I/O.

### Async/await and the event loop

**`asyncio`** achieves concurrency in *one thread* with **cooperative multitasking**: an **event loop** runs many **coroutines** (`async def` functions). At each `await` a coroutine says "I'm waiting; run someone else", and the loop resumes it when the awaited thing is ready. It is lightweight (thousands of concurrent waits), but **one blocking call freezes everything**: a synchronous `requests.get` or a long CPU loop inside an `async def` stalls every other request on that loop.

JavaScript is built on the same model: one thread, an event loop, **Promises**, and `async/await` as syntax over Promises.

**Which style does each part of this repo use, and why?**

* `services/mcp` is **async** end to end (`async def search_products`, `httpx.AsyncClient`): a tool server mostly waits on SerpAPI, so a few threads' worth of event loop serves many calls.
* The API's `routes/chat.py::send` is a plain **sync** `def`. FastAPI/Starlette runs sync endpoints in a **thread pool**, so a blocking LangGraph + psycopg call does not block the event loop. The `events()` sync generator is iterated in a thread too.
* The API's `routes/products.py::buy_link` is `async def` because it awaits the MCP client.
* The bridge: `McpProductSearch.__call__` is *sync* (the graph calls it from thread-pool workers) but the FastMCP client is *async*, so it does `asyncio.run(self._search(spec))`, which creates a **fresh event loop in that worker thread** for each call ("find_products runs searches in worker threads, so each call gets its own event loop"). Calling `asyncio.run` inside a thread that is already running a loop would fail, which is why each worker thread owns its own.

Rule: **do not mix blocking calls into async code, and do not call async code from sync code without a bridge.** If you see "RuntimeError: this event loop is already running", this is why.

### Race conditions, locks and idempotency

A **race condition** is when correctness depends on the unlucky ordering of concurrent operations. Classic: two threads read a counter, both add 1, both write back, and one increment is lost (a *lost update*). The fix is **mutual exclusion**: a **lock** so only one thread runs the critical section at a time.

Examples here:

1. **One turn per conversation.** `s.active_conversations` is a Python `set` guarded by `threading.Lock`: check membership, add, all inside `with s.active_lock:`. Without the lock, two quick clicks could both pass the check and run the agent twice on one conversation.
2. **The audit chain must not fork.** Two simultaneous appends could both read the same "previous hash" and write two entries pointing at the same parent. The Python side takes a **Postgres advisory lock** inside the transaction (`SELECT pg_advisory_xact_lock(727001)`); the TypeScript side serialises appends with a promise chain (`this.tail.then(...)`). Same problem, different tools, because the lock must live *where the shared state lives* (the database, or the single process).
3. **Migrations at startup.** If two containers start together, both could run migrations. `migrate()` takes `pg_advisory_lock(727002)` so only one proceeds (and the other then sees them already applied).
4. **Token replay.** `ReplayGuard.first_use` is a check-then-insert on a dict. In a single asyncio thread this is safe (no `await` between check and set, so no other coroutine can interleave). With several processes it would not be: each has its own dict. That is exactly the limitation the docs state and why Redis would be needed.
5. **Browser refresh.** `refreshSession()` in `api.ts` stores one in-flight Promise in `refreshing` and returns it to every concurrent caller: "Concurrent callers share one request, because each refresh replaces the cookie and a second simultaneous one would look like token theft." (React Strict Mode intentionally runs effects twice in development, which would otherwise trigger exactly that.)

**Idempotency.** An operation is **idempotent** if doing it twice has the same effect as once (`PUT x=5`, "mark as read", `get_buy_link` with a cache). Networks fail and clients retry, so *design operations to be safely repeatable* or protect them (idempotency keys, unique constraints, the `UNIQUE (conversation_id, batch, position)` constraint on outfits). The MCP tools are annotated `idempotentHint: True` so clients know retry is safe.

**Deadlock** (two parties each wait for the other's lock) is avoided by taking locks in a consistent order and holding them briefly.

### Concurrency vs parallelism

*Concurrency* is dealing with many things at once (structure); *parallelism* is doing many things at the same instant (hardware). One-thread asyncio is concurrent but not parallel. Say that precisely in interviews.

## 2.7 Resources and context managers

Resources (connections, files, locks, sockets) must be released even on error. Python's `with` statement guarantees it:

```python
with request.app.state.pool.connection() as conn:
    ...   # on normal exit the transaction commits; on exception it rolls back; the connection returns to the pool
```

A **connection pool** keeps a few open database connections and lends them out, because opening a connection is slow (TCP, TLS, authentication). `make_pool(url, min_size=1, max_size=10)`. Forgetting to return connections ("connection leak") eventually starves the app, so the pattern is always `with`.

You write your own with `__enter__/__exit__` or `@contextmanager` (`tracked()`; `DemoTools.__aenter__/__aexit__`). Async code uses `async with` (`async with self._client_factory() as client`). TypeScript has no `with`; you use `try/finally` (see `reader.releaseLock()` in `readEvents`).

## 2.8 Dependency injection and testability

Notice how `create_app(cfg=settings, pool=None, graph_factory=None, tool_client_factory=None)` accepts its collaborators as **parameters with real defaults**. In production it builds them; in tests it receives fakes (a throwaway Postgres pool, a fake LLM, a fake tool client). This is **dependency injection** without a framework: *do not construct your dependencies inside your logic; accept them.* It is the single biggest enabler of fast, offline tests (Chapter 29). FastAPI also has a built-in system (`Depends(current_user)`).

The opposite is **hidden global state**: a module that reads `settings` directly and calls the network inline can only be tested by mocking the world. The repo mostly passes `cfg` explicitly (`mint_access_token(user_id, cfg)`), with module-level `settings` only as a default.

## 2.9 Configuration (the Twelve-Factor way)

**Config** is everything that differs between environments (database address, keys, feature switches). The rule: **store config in environment variables, not in code** (the "twelve-factor app"). Benefits: the *same image* runs in dev and prod; secrets never enter git.

`services/api/src/api/config.py` uses **pydantic-settings**:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")
    database_url: str = "postgresql://stylist:stylist_dev_password@localhost:5432/stylist"
    auth_access_ttl_s: int = 900
    ...
```

Precedence: real environment variables override the `.env` file, which overrides the defaults in code. Type hints convert text to `int`/`bool`. `_find_env_file()` walks up to find a repo-root `.env` for local dev; **in a container there is no `.env` and that is fine** because compose injects real variables. Naming rule: field `database_url` is read from `DATABASE_URL` (case-insensitive).

Two good habits visible here: (1) **secure-by-default values** (`cookie_secure: bool = False` is documented "MUST be True when served over https" and the production Dockerfile sets `COOKIE_SECURE=true`); (2) **fail at startup** if a required secret is missing, not at 3 a.m. on first use.

Multi-line secrets (PEM keys) in a single-line variable use literal `\n`, and `jwt_private_key_pem` converts them back: `.replace("\\n", "\n")`. A concrete example of a *serialisation* detail that breaks real deployments.

## 2.10 Packages, environments, lockfiles, supply chain

* A **package** is reusable code you install; a **virtual environment** isolates one project's packages from another's.
* A **lockfile** (`uv.lock`, `package-lock.json`) pins the *exact* version of every direct and indirect dependency so builds are **reproducible**. Dockerfiles use `uv sync --frozen` and `npm ci`, which *fail if the lockfile and manifest disagree* instead of silently resolving new versions.
* **Semantic versioning**: `MAJOR.MINOR.PATCH`; `>=3.1.2` accepts newer minors, which can still break you in practice. Lockfiles are the protection.
* **Supply-chain risk**: every dependency is code you run with your privileges. Pin, review what you add, prefer well-maintained libraries, and keep the number small. (Chapter 21.)
* **Monorepo with workspaces**: the root `package.json` groups `apps/web` and `apps/mastra` so one `npm install` serves both.
* **Version traps are normal.** The repo's guide records two: FastMCP 4's client expects `httpx2` auth objects (not `httpx`), and `run()` takes `host=`/`port=` directly. *Lesson in the guide's own words: "Version differences like this are why you run things instead of trusting examples from the internet."*

## 2.11 Code quality habits that interviewers notice

* **Names say what, comments say why.** `clamp_to_budget`, `host_allowed`, `all_public`. Comments in this repo explain *reasons* ("a fast hash is fine here: the input is 384 random bits").
* **Small functions with one job**, flat control flow, early returns for the error case.
* **Make illegal states unrepresentable** with types (`Literal`, enums, non-optional fields).
* **Lint and format automatically** (`ruff` for Python; `tsc --noEmit` for TypeScript). A linter that runs in CI ends style arguments.
* **Tests as documentation.** `test_a_token_holds_no_secret_material` states a requirement in its name.
* **Delete code you do not need.** The Mastra gateway was dropped rather than kept "just in case".

## 2.12 A debugging method

1. **Reproduce** reliably. If you cannot reproduce, you cannot know you fixed it.
2. **Read the actual error.** All of it, including the bottom of a Python traceback (the *last* line is the exception; the line above it is where it happened).
3. **Form a hypothesis, predict what you would see if true, and test it** (print, log, a debugger, a minimal script). Change one thing at a time.
4. **Bisect**: halve the search space (comment out half, `git bisect`).
5. **Check assumptions** about environment: versions, which environment variables are really set (print their *names*, never secret values), which file is actually loaded.
6. **Fix the cause, add a test that would have caught it, and look for the same bug elsewhere.**

Real examples from this repo's history: a script that wrote a rupee sign crashed halfway on Windows because Python opened the file in the legacy `cp1252` encoding, leaving a file empty (always pass `encoding="utf-8"`, and do not open a file for writing before the content is ready). Backslashes were silently stripped when code containing `\n` went through a shell here-document (write such files with an editor tool instead). A first request hanging ~40 seconds turned out to be an **IPv6 stall** on some networks, fixed by binding outbound connections to `0.0.0.0` (IPv4), the `force_ipv4` setting. These are *environment* bugs, the kind FDEs meet every week on customer machines.

## 2.13 JavaScript/TypeScript essentials used in this repo

* `const`/`let`; arrow functions `(x) => x + 1`; template strings `` `${API}${path}` ``.
* **Optional chaining and nullish coalescing:** `a?.b` (undefined if `a` is null), and `a ?? b` (use `b` only if `a` is `null`/`undefined`). Contrast `||`, which also replaces `0` and `''`. This matters in `api.ts`: `process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'`. In the Docker build, `NEXT_PUBLIC_API_URL` is set to an **empty string** (meaning "same origin"), and `??` correctly keeps the empty string; `||` would have wrongly replaced it with localhost. A one-character difference with deployment consequences.
* `refreshing ??= (async () => {...})()` is **logical nullish assignment**: assign only if currently null/undefined (an in-flight-promise cache).
* **Modules**: `import`/`export`; Node and bundlers resolve them.
* **`Promise.all`** for parallel awaits; `await` inside a loop is sequential.
* **Immutability in React state**: `setMessages((m) => [...m, newMessage])` builds a *new* array instead of mutating (Chapter 19).

## Common mistakes

* Treating assignment as copying; mutating arguments.
* `await`-less async calls (forgetting `await` returns a coroutine, not a result).
* Blocking calls inside `async def`.
* Catching `Exception` and moving on; leaking internal error text to users.
* Unbounded in-memory structures fed by outside input.
* Reading config from code constants instead of the environment.
* Using `==` for comparing secrets (use constant-time `hmac.compare_digest`, as `/metrics` does).

## Summary

* Variables are references; mutate carefully, copy deliberately.
* Validate untrusted data into typed objects at the boundary (Pydantic, zod).
* Functions are values: closures, decorators and injected factories give flexible, testable design.
* Generators and async generators make streaming natural.
* Exceptions: catch narrowly, log, show users safe text, and let some failures be *return values*.
* AI apps are I/O-bound: use threads or async for waiting; protect shared state with locks that live where the state lives.
* Configuration belongs in the environment; dependencies belong in lockfiles.

## Key terms

*process, thread, stack, heap, reference, mutable, closure, decorator, generator, event loop, coroutine, GIL, race condition, lock, idempotent, context manager, dependency injection, twelve-factor, lockfile.*

## Interview questions

1. What does `b = a` do for a list in Python? How do you copy a nested structure?
2. What is the difference between concurrency and parallelism? Where does the GIL matter?
3. When would you choose threads, asyncio or multiprocessing? What does an AI API server mostly need?
4. A request handler is `async def` but calls `requests.get`. What happens to other requests?
5. Explain a race condition and give two ways to prevent one. (Locks; atomic operations; database constraints.)
6. Why return a status instead of raising an exception in `accounts.rotate`?
7. What is a closure? Show one in this repo.
8. What does `??` do in JavaScript and how does it differ from `||`?

## Exercises

1. Write a decorator `@timed` that logs how long a function took. Apply it to `verify_product` and read the timings in a test.
2. Rewrite `find_products_for_specs`'s parallel search using `asyncio.gather` instead of `ThreadPoolExecutor`. What must change in `McpProductSearch`? (Hint: remove `asyncio.run`.)
3. Create a race: write a script where 100 threads each do `counter += 1` 10,000 times with no lock, then add a lock and compare.
4. Add a `bool` setting to `config.py`, set it through `.env` and through a real environment variable, and prove which one wins.
5. In `apps/web/lib/sse.ts`, change `{ stream: true }` to `{ stream: false }` and run `npm test -w apps/web`. The existing test "keeps unicode (the rupee sign) intact even when a character is split between chunks" should fail; explain exactly why, then restore the line.
