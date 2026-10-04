# Chapter 9. Agents and LangGraph

> **Learning objectives.** Distinguish workflows from agents and choose between them; know the main agent patterns and failure modes; understand LangGraph (state, reducers, nodes, edges, checkpointers, threads, interrupts, streaming) deeply enough to rebuild this project's graph from scratch; design human-in-the-loop flows over stateless HTTP; and know the alternatives (plain code, other frameworks, durable-workflow engines).
>
> **Prerequisites.** Chapters 2, 3 (graphs), 7, 8.

---

## 9.1 What is an agent?

There is no single agreed definition. A useful engineering one:

> An **agent** is a system in which a language model **decides what to do next** (which tool to call, whether to continue or stop), repeatedly, in a loop, based on the results of earlier steps.

Contrast with a **workflow**, where **your code** fixes the sequence of steps and the model only fills in individual steps (extract, classify, write).

| | Workflow | Agent |
|---|---|---|
| Control flow decided by | your code | the model, at run time |
| Predictability | high | lower |
| Cost / latency | bounded, known | variable, can spiral |
| Testing | straightforward | harder (non-deterministic paths) |
| Best for | tasks you can describe as steps | open-ended tasks with unpredictable steps |
| Failure modes | a step is wrong | wanders, loops, picks wrong tools, compounds errors |

**The most important design rule in this chapter: start with the simplest thing that works.** A single well-prompted model call beats a workflow when it is enough; a workflow beats an agent when you know the steps; reach for an autonomous agent only when the task genuinely needs open-ended exploration *and* the value justifies the cost and the risk *and* errors can be caught and recovered. Most production "agents" that succeed are in fact **workflows with a few model-driven steps and strong guardrails**.

### Common workflow patterns (know the vocabulary)

1. **Prompt chaining**: output of one call feeds the next (`extract → propose → plan`).
2. **Routing**: a classifier call sends the input to a specialised path or model.
3. **Parallelisation**: run independent calls at once (sectioning), or run the same call several times and vote.
4. **Orchestrator-workers**: a lead model breaks the task down dynamically and delegates to worker calls.
5. **Evaluator-optimiser (reflection)**: one call produces, another critiques, loop until good enough (bounded!).

### Agent patterns

* **Tool-calling loop (ReAct-style)**: think → act (call a tool) → observe → repeat until done. The core of coding agents and research agents.
* **Plan-and-execute**: first make a plan, then execute steps (re-planning as needed). More predictable than pure ReAct.
* **Reflection/self-critique**: review and fix its own output.
* **Multi-agent systems**: a **supervisor** routes among specialised agents, or agents **hand off** to each other. Appealing, but each agent adds cost, context duplication and failure modes; prefer one agent with good tools until measurement says otherwise.
* **Human-in-the-loop (HITL)**: the agent pauses for approval or missing information. Essential for risky actions, and used in this project for questions and style choice.
* **Memory**: *short-term* (the current thread's state and messages) and *long-term* (facts about the user or past outcomes stored externally and retrieved).

### What this project is

AI Stylist is an **agentic workflow**: a fixed graph of eight nodes where the model is used inside three nodes (extract preferences, propose styles, plan outfits), **code** performs searching, verification, ranking and budget enforcement, the user is inserted at two **interrupt** points, and a **bounded replan loop** lets the system recover from weak search results. The model never chooses tools. That is a deliberate, defensible choice: the task has known stages, correctness matters (budget, men's clothing, verified products), and cost is tight.

### Failure modes of agents (and the controls)

| Failure | Control |
|---|---|
| Infinite or very long loops | Iteration cap; recursion limit; wall-clock timeout; token/cost budget |
| Wrong tool or wrong arguments | Fewer, clearer tools; strict schemas; validate arguments in code; deterministic routing where possible |
| Error compounding (a small early mistake poisons later steps) | Validate after each stage; checkpoint; verify with deterministic checks |
| Context bloat (every observation appended forever) | Summarise or trim; return concise tool results; clear old results |
| Goal drift / forgetting constraints | Restate constraints each step; keep state explicit (structured) rather than only in chat |
| Unsafe actions | Least privilege; human confirmation; read-only defaults; sandbox |
| Non-reproducibility | Log every step; seed where possible; record prompts, tools, results (traces) |
| Cost explosions | Budgets and alerts per run, per user, per day (this app: rate limits, credit caps) |
| Prompt injection via observations | Treat tool output as untrusted; limit capabilities (Chapters 8, 21) |

## 9.2 LangChain in two minutes

**LangChain** is a library of building blocks for LLM apps; **LangGraph** (built by the same team) is a lower-level framework for **stateful, multi-step, controllable** agent workflows. This project uses LangChain for:

* **Messages**: `SystemMessage`, `HumanMessage`, `AIMessage` (and `ToolMessage`), the typed form of chat roles. They carry `.content` and `.type` (`"human"`, `"ai"`).
* **Chat model wrappers**: `ChatOpenAI` (works with any OpenAI-compatible endpoint).
* **`with_structured_output(schema, method=...)`**: returns a runnable that calls the model and parses the result into your Pydantic class (Chapter 7).
* **Runnables**: objects with `invoke`, `stream`, `batch` and async variants; composed with `|` (LCEL). The graph's `.invoke`/`.stream` are runnables too.

You can build agents without LangChain at all (Section 9.9). It is a convenience layer, and it evolves quickly; keep your use thin (this repo isolates it in `llm.py`, `graph.py`, `telemetry.py`).

## 9.3 LangGraph: the model

LangGraph represents an application as a **graph**:

* **State**: the shared data structure the whole run reads and updates.
* **Nodes**: functions that read the state and return updates.
* **Edges**: which node runs next (fixed or conditional).
* **Checkpointer**: saves the state after each step, enabling pause/resume, persistence, time travel and fault tolerance.

Underlying idea (inspired by Google's Pregel): execution proceeds in **super-steps**. In each, the nodes that are ready run (in parallel if several), their outputs update the state, then the next set of nodes is chosen. State is saved at every super-step boundary.

### State

```python
from typing import Annotated, TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class StylistState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], add_messages]   # reducer: append, never overwrite
    prefs: dict
    missing: list[str]
    styles: list[dict]
    chosen_style: dict | None
    outfit_specs: list[dict]
    outfits: list[dict]
    notes: list[str]
    rejected: list[dict]
    search_errors: list[str]
    retries: int
```

State can be a `TypedDict`, a dataclass or a Pydantic model. Each key is a **channel**. Design guidance:

* Keep state **small, explicit and serialisable** (it is written to the database at every step, so large blobs are expensive).
* Store **structured** data (`prefs`, `outfits`) rather than only chat text; the model is a poor database.
* Use plain `dict`s (`model_dump()` output) for things that must serialise easily; this repo stores `outfits` as dicts and re-validates with `Outfit.model_validate(...)` when needed.

### Reducers: how updates merge

A node returns a **partial update**. For each key returned, LangGraph either **overwrites** the channel value (the default) or merges using a **reducer** specified with `Annotated[type, reducer]`.

* `messages` uses `add_messages`: **append** new messages (and replace one with the same id), and convert shorthand tuples such as `("user", "hello")` into `HumanMessage`. This is why a node can return `{"messages": [AIMessage(...)]}` and the history grows.
* `prefs`, `outfits`, `notes` have **no reducer**: whatever a node returns **replaces** the previous value. That is why `gather_prefs` builds a full merged dict (`prefs = dict(state.get("prefs") or {})`; `prefs.update(...)`) and returns the whole thing; and why `find_products` returns the *concatenated* outfits list (`list(existing) + new`).
* `operator.add` is a common reducer for list accumulation; custom reducers are just functions `(old, new) -> merged`.

**Pitfall:** forgetting that a missing reducer means *replace*. If two parallel nodes both return `outfits`, one overwrites the other, or LangGraph raises an error about concurrent updates. Use a reducer when parallel branches write the same key.

### Nodes

A node is a function `state -> partial update` (sync or async):

```python
def gather_prefs(state: StylistState):
    extracted = structured(PrefsExtraction, load_prompt("extract_prefs"), history=state["messages"])
    prefs = dict(state.get("prefs") or {})
    prefs.update({k: v for k, v in extracted.model_dump().items() if v is not None})
    return {"prefs": prefs, "missing": [f for f in REQUIRED_PREFS if f not in prefs]}
```

Properties of a good node: **single responsibility**, **returns only what it changes**, **does not mutate its input**, **idempotent where possible** (it may be re-run after a failure or resume), and **records decisions in state** (`missing`) so edges stay simple.

### Edges

```python
g.add_edge(START, "gather_prefs")                                  # unconditional
g.add_conditional_edges("gather_prefs", after_gather, ["ask_user", "propose_styles"])
```

A **conditional edge** calls a routing function with the state and returns the name of the next node (or list of names, for fan-out). The third argument documents the possible targets (helps visualisation and validation). Routing functions should be **pure and cheap**, reading only state, so the flow is testable without a model:

```python
def after_gather(state):  return "ask_user" if state["missing"] else "propose_styles"

def after_validate(state):
    if state.get("search_errors"):                       return "respond"      # replanning cannot help
    if len(state["outfits"]) >= OUTFITS_WANTED or state.get("retries", 0) > MAX_RETRIES:
        return "respond"
    return "plan_outfits"                                                       # loop back (bounded)
```

Other control tools: **`Command(goto=..., update=...)`** returned from a node to update state *and* choose the next node in one step; **`Send(node, payload)`** for dynamic fan-out (map-reduce: run the same node on N items in parallel); **subgraphs** (a compiled graph used as a node); **`RetryPolicy`** per node (retry transient exceptions with backoff); and a **recursion limit** (a hard cap on super-steps per run, the safety net against runaway loops: do not rely on it alone, *design* termination).

### Compile and run

```python
graph = g.compile(checkpointer=checkpointer)
graph.invoke(input, config)                         # run to completion (or until interrupt); returns final state
for chunk in graph.stream(input, config, stream_mode="updates"): ...
```

**Stream modes** control what you receive:

| Mode | You get |
|---|---|
| `values` | the full state after each step |
| `updates` | `{node_name: update}` after each node (what this app uses for progress labels) |
| `messages` | LLM tokens as they are generated (for token streaming to a UI) |
| `custom` | anything your nodes emit with a writer |
| `debug` | detailed internals |

### Checkpointers, threads, persistence

A **checkpointer** saves a **checkpoint** (the state plus what runs next) after each super-step, keyed by a **thread id** supplied in the run config:

```python
config = {"configurable": {"thread_id": "7f2c..."}}
```

Implementations: `MemorySaver` (in-process; tests and demos), SQLite and **Postgres** savers (durable). This repo uses `PostgresSaver`, whose `setup()` creates its own tables on first start. Consequences you get *for free*:

1. **Memory across turns**: invoke again with the same `thread_id` and the state (including the message history) is restored.
2. **Pause and resume across processes and restarts**.
3. **Fault tolerance**: after a crash, resume from the last checkpoint.
4. **Time travel / debugging**: list a thread's checkpoint history, inspect any past state, edit state (`update_state`) and replay from there.
5. **Human-in-the-loop** (below).

`graph.get_state(config)` returns a **snapshot**: `.values` (current state), `.next` (nodes about to run), `.tasks` (pending tasks, each with its `.interrupts`), plus metadata and config. The API uses it to read history and to detect whether the graph is **waiting for the user**.

**Operational notes from this repo:**
* LangGraph's Postgres saver **requires autocommit connections**, so the app creates a **second connection pool** (`autocommit=True`, size 1-5) just for it, separate from the transactional pool used by request code. (Two pools, two transaction models.)
* **Thread id = conversation id** (`str(row["id"])`), so a conversation row in the app's own tables and a checkpoint thread are the same identity. Anything that makes two concepts share one id (and one lifecycle) removes a whole class of bookkeeping.
* The compiled graph is **rebuilt per request** (`graph_factory(user_id, stats)`), because its model and search wrappers are *per user and per request* (counters, identity). Building is cheap; the **state lives in the checkpoint, not in the graph object**.

### Interrupts: human in the loop

```python
from langgraph.types import interrupt, Command

def wait_for_choice(state):
    choice = interrupt({"type": "choose_style", "styles": state["styles"]})   # PAUSES here
    ...                                                                         # runs after resume
```

**Semantics (get these exactly right; they are an interview favourite):**

1. `interrupt(payload)` **raises a special pause**. LangGraph saves the checkpoint and **returns control to the caller**, surfacing `payload` (in `stream` as an `__interrupt__` update; in the snapshot under `.tasks[i].interrupts`).
2. Nothing is running now. No thread is blocked, no HTTP request is held open. The conversation is just *rows in Postgres*.
3. To continue, call the graph again with the same thread id and `Command(resume=value)`.
4. **The interrupted node re-executes from its first line**, and this time `interrupt(...)` **returns `value`** instead of pausing.

Point 4 has a sharp consequence: **any code before `interrupt()` in the node runs twice** (once before the pause, once on resume). Therefore: put side effects (sending an email, charging a card, writing a record) *after* the interrupt, or make them idempotent, or put the interrupt in its own small node (which is exactly what `ask_user` and `wait_for_choice` are: they do nothing but ask and record the answer). With multiple `interrupt()` calls in one node, resume values are matched **by order**.

## 9.4 This project's graph, node by node

```
START → gather_prefs ──missing?──► ask_user ──► (back to gather_prefs)
                       └─ok───────► propose_styles → wait_for_choice → plan_outfits → find_products
                                                                  ▲                       │
                                                  (fewer than 4, bounded)                 ▼
                                                                  └──── rank_and_validate ── respond → END
```

### State flow at a glance

| Node | Reads | Writes | Model? | Pauses? |
|---|---|---|---|---|
| `gather_prefs` | `messages`, `prefs` | `prefs`, `missing` | yes (extract) | no |
| `ask_user` | `missing` | `messages` (+ question, + answer) | no | **yes** (`ask`) |
| `propose_styles` | `prefs` | `styles` | yes | no |
| `wait_for_choice` | `styles` | `chosen_style` | no | **yes** (`choose_style`) |
| `plan_outfits` | `prefs`, `chosen_style`, `outfits`, `notes` | `outfit_specs`, `notes` (cleared) | yes (plan) | no |
| `find_products` | `outfit_specs`, `prefs`, `outfits` | `outfits`, `notes`, `rejected`, `search_errors` | **no** | no |
| `rank_and_validate` | `outfits`, `prefs` | `outfits` (filtered), `retries` | no | no |
| `respond` | `outfits`, `chosen_style`, `search_errors` | `messages` | no | no |

Only three of eight nodes call the model; the rest are deterministic code. That ratio is a healthy sign.

### `gather_prefs` and `ask_user`: slot filling with HITL

`gather_prefs` asks the model to extract `budget_inr` and `occasion` from the conversation, **merges** into the existing prefs (a new message that mentions only the occasion must not erase the budget), and computes `missing` from `REQUIRED_PREFS = ["budget_inr", "occasion"]`. `after_gather` routes on that list. If something is missing, `ask_user` picks the **first** missing field, looks up a **fixed question string** (`_QUESTIONS`), calls `interrupt({"type": "ask", "question": ..., "missing": ...})`, and on resume appends *both* the question (`AIMessage`) and the answer (`HumanMessage`) to the history. Edge back to `gather_prefs` re-extracts from the now-longer conversation.

Design notes:
* **The question text is a constant, not generated by the model.** Predictable, free, testable, and the evals can assert on it (`fieldAsked` in the TypeScript harness detects "budget"/"occasion" in the question).
* **Gender is not asked and not in `REQUIRED_PREFS`** (menswear only).
* **The loop terminates** because each pass either fills a field or the user's answer cannot fill it; in the latter case the agent asks again (the user is the bound). Production hardening: cap re-asks per field and offer defaults.

### `propose_styles` and `wait_for_choice`

The model returns a `StyleList` (five `StyleOption`s). The node stores them as dicts. `wait_for_choice` interrupts with the list. On resume, `choice` is whatever the UI sent: **a style id** (when a card is clicked: the UI sends `s.id`) **or free text** ("something like old money"). Code matches case-insensitively against `id` and `name`; anything else becomes a `custom` style whose description is the user's text, which the *planner* will interpret. Handling *both* structured and free-form answers at one interrupt is a good UX contract.

### `plan_outfits`

Builds a context dict (`preferences`, `chosen_style`, `outfits_needed`, `already_chosen` rationales, `planner_notes`), calls the planner with `plan_outfits.v2`, takes `plan.outfits[:need]` (never more than needed, whatever the model returned), **clamps each spec's caps to the budget in code**, and clears `notes` (they have been consumed). `need = OUTFITS_WANTED - len(existing)` is what makes the **replan loop incremental**: on the second pass the agent only asks for the missing outfits, and `already_chosen` tells the model what to avoid repeating.

### `find_products`: code, not a model

Calls `find_products_for_specs` (Chapter 11): parallel searches, verification, greedy selection, de-duplication across outfits (it passes `exclude_urls` of products already used). It returns new outfits **appended** to the existing ones, **notes** for the planner (`"Spec 2 (chinos): no verified match for 'peach chinos'"`), the `rejected` list (debugging), and `search_errors` (shopper-safe messages).

### `rank_and_validate`: the second line of defence

Re-filters outfits with `total_inr <= budget and _outfit_is_verified(o)` (each item must have `verification.is_match`), sorts confirmed (`confidence == "high"`) first with a **stable** sort, and increments `retries` if fewer than four remain. This looks redundant with `find_products`, and it is, **on purpose**: *the last node before the user checks the invariants the earlier nodes were supposed to guarantee*, so a future bug in any earlier step cannot put a wrong outfit on screen (**defence in depth** inside the workflow).

### `respond`

Plain Python formats the summary (no model call) and handles three cases: nothing found because search itself failed (apologise, do not blame the user), found fewer than four with or without errors (explain honestly), or success. Code writing user-facing text where precision matters (prices, totals) avoids model arithmetic and hallucinated details.

### Termination and bounds

`after_validate` ends the loop when: search errors exist; four outfits exist; or `retries > MAX_RETRIES` (2). Together with `MODEL_ATTEMPTS = 3`, `ATTEMPTS = 2` in the MCP client, and the worker-pool size, the total work per conversation has a **hard upper bound** you can compute, which is exactly what you want when each unit costs money.

## 9.5 How the API drives the graph (`routes/chat.py`)

This is where graph semantics meet HTTP.

```python
snapshot = graph.get_state(config)
resuming = pending_interrupt(snapshot) is not None
payload = Command(resume=body.text) if resuming else {"messages": [("user", body.text)], **FRESH_ROUND}
...
for update in graph.stream(payload, config, stream_mode="updates"):
    for node, value in update.items():
        if node == "__interrupt__":  yield sse("interrupt", value[0].value)
        elif node in STAGE_LABELS:   yield sse("status", {...})
```

Walk through three situations:

1. **A fresh conversation, first message.** No pending interrupt → payload is a new user message plus `FRESH_ROUND` (reset `outfits`, `outfit_specs`, `notes`, `retries`, `search_errors`, `styles`, `chosen_style`). Note `prefs` is **not** reset: a returning shopper's budget carries over, and `gather_prefs` merges new information into it.
2. **The graph is paused at `ask_user` or `wait_for_choice`.** The user's text is sent as `Command(resume=text)`; the interrupted node continues. The stream's first events come from the resumed node.
3. **The conversation finished earlier; the user asks again.** No pending interrupt → the same path as case 1: a *new round* in the same thread, which re-runs from `START`, with the old messages still in history.

Further details worth studying:

* **`pending_interrupt(snapshot)`** scans `snapshot.tasks[*].interrupts`. The same function powers `GET /conversations/{id}` so a page reload re-shows the unanswered question or style cards (`"pending": ...`).
* **Streaming `updates`** yields after each node; the API converts each into an SSE `status` event with **duration since the previous update** (steps run sequentially, so the difference is that step's time) for the UI timeline and Prometheus histograms.
* **After the stream ends**, `graph.get_state(config)` is read to decide whether the turn finished (`respond` ran, no pending interrupt) and to persist outfits and emit `outfits` and `message` events. **The database writes happen in the API, not in graph nodes**, keeping the graph pure of persistence concerns and the app's tables under the API's control.
* **Concurrency control**: one turn at a time per conversation (a locked set), released in `finally` even if the browser disconnects.
* **Error handling**: any exception becomes an `error` event with a friendly message and an audit entry (type only), and the `done` event always follows with the outcome (`ok`, `waiting_for_user`, `no_outfits`, `error`) and stats.

### What you get from persistence, concretely

* Close the laptop mid-conversation; open it tomorrow; the style cards are still waiting.
* Restart the API container; no conversation is lost.
* Support can read a thread's checkpoint history to see exactly what the agent knew at each step (while remembering this contains user content, so access must be controlled and audited).

## 9.6 Designing human-in-the-loop flows

* **Pause, do not wait.** In stateless web architectures you cannot keep a request open for a human. Persist state, return, resume on the next request.
* **Make the pause part of the API contract.** Here: an `interrupt` SSE event, a `pending` field in the history response, and a resume path that accepts text.
* **Design the question as data**, not just text: `{"type": "choose_style", "styles": [...]}` lets the UI render cards while a simple text channel still works.
* **Accept free-form answers**, and decide what to do with unexpected ones (here: treat as custom style).
* **Be idempotent on resume**, since the node re-runs from the top.
* **Guard against abandoned threads**: expire or ignore stale pending states; limit new conversations per day (this app: 30).
* **Approval gates for risk** (payments, deletions, emails): present the exact action and arguments, require explicit approval, log who approved what (audit).

## 9.7 Alternatives and when to choose them

| Option | Idea | Choose when |
|---|---|---|
| **Plain Python code** | functions and `if`/`while` | the flow is simple; you want zero framework risk. A manual tool-calling loop is ~30 lines |
| **LangGraph** | explicit state machine with persistence and interrupts | long-running, branching, resumable, human-in-the-loop flows; need durable state; want streaming and visualisation |
| **Provider agent SDKs** (OpenAI Agents SDK, Claude Agent SDK, Google ADK) | loop, tools, handoffs, guardrails provided by the vendor | you are committed to one vendor and want batteries included |
| **LlamaIndex Workflows** | event-driven steps | retrieval-heavy apps in the LlamaIndex ecosystem |
| **CrewAI / AutoGen / similar** | role-based multi-agent teams | prototypes of multi-agent collaboration; check maturity and observability before production |
| **Pydantic AI** | typed agents with Pydantic at the centre | you want type-safe outputs and dependency injection in Python |
| **Mastra** (TypeScript) | TS-native agents, workflows, evals, storage, observability | your team is TypeScript-first. *This project evaluated it as a gateway and chose instead to use it for evals and tracing (Chapter 15).* |
| **Durable workflow engines** (Temporal, Inngest, Airflow, Prefect, Step Functions) | exactly-once-ish execution, retries, timers, long-running orchestration | business-critical processes that run for hours/days, with or without LLM steps; they complement agent frameworks |

Selection criteria: **state and persistence needs**, **human-in-the-loop**, **streaming**, **observability and evals integration**, **language**, **team familiarity**, **lock-in**, **maturity and API stability** (agent frameworks churn; budget for upgrades), and **how much of the framework you actually use**. An FDE must be comfortable *with and without* frameworks; in a customer environment you may be told "no new dependencies".

## 9.8 Guidelines for building agents that work

1. **Start with a single call; add structure only when evals show you need it.**
2. **Model the state explicitly** (structured fields), not only as chat text.
3. **Keep the model out of decisions code can make** (budget math, dedup, routing on state).
4. **Bound every loop** by iterations, time, tokens and money, and compute the worst case.
5. **Verify after each risky step** with deterministic checks; fail closed.
6. **Minimise tools and their power**; read-only first; confirm destructive actions.
7. **Return small, structured tool results**; do not let observations balloon the context.
8. **Make every run observable**: trace ids, per-step timing, call counts, cost; store prompts and versions (Chapter 13).
9. **Build offline fakes** for the model and tools so the graph can be tested in milliseconds (this repo's `ScriptedLLM`, `mock_search`, `FakeLLM`).
10. **Evaluate end to end** with realistic scenarios and measurable guarantees (Chapter 12).
11. **Design for failure**: provider outages, rate limits, malformed output, partial results; always give the user an honest, useful message.
12. **Prefer idempotent steps** so resume/retry is safe.
13. **Keep prompts and schemas versioned and pinned.**
14. **Separate orchestration from persistence from presentation** (graph vs repo vs routes).

## 9.9 Code you should be able to write

### A manual tool-calling agent loop, with no framework (OpenAI-compatible)

```python
import json
from openai import OpenAI

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=KEY)
TOOLS = [{"type": "function", "function": {
    "name": "add", "description": "Add two integers.",
    "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                   "required": ["a", "b"], "additionalProperties": False}}}]
IMPLS = {"add": lambda a, b: a + b}

def run(question: str, max_steps: int = 5) -> str:
    messages = [{"role": "user", "content": question}]
    for _ in range(max_steps):                                   # BOUND the loop
        reply = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS).choices[0].message
        messages.append(reply)
        if not reply.tool_calls:
            return reply.content                                 # final answer
        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments)       # parse...
                result = IMPLS[call.function.name](**args)       # ...validate/dispatch (allow-list of tools!)
            except Exception as exc:
                result = f"error: {exc}"                         # let the model see and recover from the failure
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)})
    return "Stopped: too many steps."
```

### A tiny LangGraph with a checkpointer and an interrupt

```python
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

class S(TypedDict, total=False):
    name: str
    greeting: str

def ask(state: S):
    name = interrupt({"type": "ask", "question": "What is your name?"})   # pauses here
    return {"name": name}

def greet(state: S):
    return {"greeting": f"Hello, {state['name']}!"}

g = StateGraph(S)
g.add_node("ask", ask); g.add_node("greet", greet)
g.add_edge(START, "ask"); g.add_edge("ask", "greet"); g.add_edge("greet", END)
app = g.compile(checkpointer=MemorySaver())

cfg = {"configurable": {"thread_id": "t1"}}
app.invoke({}, cfg)                                    # runs until the interrupt, returns
print(app.get_state(cfg).tasks[0].interrupts[0].value) # {'type': 'ask', ...}
print(app.invoke(Command(resume="Ravi"), cfg))         # {'name': 'Ravi', 'greeting': 'Hello, Ravi!'}
```

Swap `MemorySaver()` for `PostgresSaver` and the same pause survives a restart. Try: add a counter to a node's state and see how it behaves across resumes; add a `print` before `interrupt` and observe it runs twice.

## 9.10 Testing agents

* **Unit-test nodes and routers** with hand-built state dicts (no model, no graph).
* **Graph tests with `MemorySaver` and a fake model** (`FakeLLM` in `tests/test_agent.py`): feed a message, assert the interrupt payload, resume, assert the outfits. `tests/test_http.py` goes one level up: the *whole HTTP API* with a real throwaway Postgres, a fake model and fake search.
* **Property tests**: budget never exceeded; every shown item verified; no duplicates.
* **Replay**: store real conversations (with consent) and rerun them against new prompt/model versions.
* **Live evals** on a schedule with real models (Chapter 12).
* **Chaos tests**: make the search fail, return empty, return malformed data, time out; assert the user still gets an honest message and the conversation is not stuck.

## 9.11 Multi-agent systems, honestly

Reasons to split into several agents: **context isolation** (a research sub-agent reads 50 pages without polluting the main thread), **parallelism**, **specialised prompts/tools/models**, and **security separation** (an agent that reads untrusted web pages should not hold the keys to destructive tools). Costs: more tokens (context is duplicated), more latency, hard-to-debug emergent behaviour, and error compounding across hand-offs. Rule of thumb: **one agent with good tools first; split only along a clear boundary that you can state and measure.**

## Common mistakes

* Building an autonomous agent when a workflow would do.
* Unbounded loops with no cost cap.
* Side effects before an `interrupt()` in the same node.
* Forgetting reducers (updates silently overwrite) or mutating state in place.
* Storing huge blobs in state.
* Letting the model do arithmetic, dedupe or authorisation.
* Not reproducing state when debugging (no checkpoint inspection, no traces).
* Tight coupling between graph nodes and web or database code.
* Testing only with the real model (slow, flaky, expensive).

## Summary

* Workflows (code decides) are more predictable than agents (model decides); start simple and add autonomy only with evidence.
* LangGraph = state + reducers + nodes + edges + checkpointer; super-steps; thread ids give persistence and memory; interrupts pause and resume (the interrupted node re-runs from its top).
* The stylist graph has three model nodes and five code nodes, two interrupts, and a bounded replan loop, with defence-in-depth validation before anything reaches the user.
* The API drives the graph with `Command(resume=...)` or a fresh payload, streams `updates` as SSE, and persists results itself.
* Bound loops, verify deterministically, minimise tool power, observe everything, test offline.

## Key terms

*agent, workflow, ReAct, tool loop, plan-and-execute, reflection, supervisor, HITL, StateGraph, state, reducer, node, edge, conditional edge, super-step, checkpointer, thread id, snapshot, interrupt, `Command`, subgraph, `Send`, stream mode, recursion limit, idempotent node.*

## Interview questions

1. What is the difference between a workflow and an agent? Which is this app?
2. Explain LangGraph's state, reducers and checkpointers. What happens when two nodes return the same key?
3. What exactly happens when a node calls `interrupt()` and the user answers hours later? What runs twice?
4. How would you implement "ask the user a question" in a stateless web service?
5. How do you stop an agent loop from running away? Name four controls.
6. Why does `rank_and_validate` re-check what `find_products` already checked?
7. When would you pick a durable-workflow engine over LangGraph?
8. How do you test an agent without calling a real model?
9. What are the downsides of multi-agent designs?

## Exercises

1. Reproduce the tiny graph in 9.9, then add a conditional edge that loops back to `ask` if the name is empty (with a retry cap of 3).
2. Draw the stylist graph's state table by hand from the code (which node writes which key), then check against `graph.py`.
3. Add a node `refine` that, when the user types "make it cheaper", lowers the budget by 20% and re-runs planning (the "make cheaper" follow-up that is listed as not yet built). Define the interrupt, state change, and evals.
4. Use `app.get_state_history(cfg)` on a conversation and print each checkpoint's `next` and `values` keys. Edit one with `update_state` and replay.
5. Replace the planning model call with a deterministic stub and prove with a test that the whole API still delivers four outfits within budget. Which guarantees are now independent of the model?
