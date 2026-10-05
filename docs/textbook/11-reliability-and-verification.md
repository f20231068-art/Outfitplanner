# Chapter 11. Reliability and Verification: "The Model Proposes, Code Disposes"

> **Learning objectives.** Design AI systems whose outputs can be trusted *because of the system around the model*; build a deterministic verifier with evidence and three-valued logic; apply layered defences (constrain, validate, verify, enforce, re-check, degrade honestly); handle failures (timeouts, retries, partial results); and read `agent/verify.py` and `agent/find.py` line by line, including their limitations.
>
> **Prerequisites.** Chapters 3, 7, 9.

---

## 11.1 The core principle

> A language model is a powerful, creative, **unreliable** component. Build the system so that **no unverified model output can reach a user or cause an action.**

Everything in this chapter is a way of making that sentence true. The model is allowed to be *wrong* as long as the system **detects** the wrongness (verification) or **cannot be harmed by it** (limits, least privilege, human confirmation).

In AI Stylist the model's job is to *propose*: preferences, style names, outfit plans. The code's job is to *dispose*: decide which proposals are acceptable. A product is shown **only if** a deterministic function says it matches what was requested. A wrong colour, a women's item, or an over-budget outfit is a **product defect**, and the system is built so those defects are *impossible by construction*, not merely unlikely.

## 11.2 The reliability stack in this app

Six layers, from the model outward. Each catches what earlier layers miss.

| Layer | Question | Mechanism | Where |
|---|---|---|---|
| 1. **Constrain** | Can we make malformed output unlikely? | Structured output via tool-calling; enums (`Literal`); field descriptions | `schemas.py`, `with_structured_output` |
| 2. **Validate** | Is the output the right shape and type? | Pydantic validation; before-validators cleaning "None"/"4k"; bounded retry (`MODEL_ATTEMPTS = 3`) | `schemas.py`, `graph.structured` |
| 3. **Enforce** | Are hard rules respected regardless of the model? | `clamp_to_budget`; take at most `need` outfits; allow-list of retailers; price cap in the search tool | `graph.py`, `search_products.py` |
| 4. **Verify** | Does each real-world object match the request, with evidence? | `verify_product` for every candidate; best-verified selection; duplicates and stock checks | `verify.py`, `find.py` |
| 5. **Re-check** | Did the earlier steps do their job? | `rank_and_validate`: totals within budget, every item carries a passing report | `graph.py` |
| 6. **Degrade honestly** | If we cannot deliver, what do we say? | `respond` handles search outage, partial results; `confidence` badge; friendly errors | `graph.py`, `chat.py`, UI |

Outside the agent, more controls bound the damage of anything that still goes wrong: auth, ownership checks, rate limits, credit caps, audit log, metrics (Parts V and III).

## 11.3 The verifier: design principles

`agent/verify.py` opens with its own design rules; they generalise to any "check an AI or scraped result against a request" problem:

1. **It reads only scraped data.** Title, description, page-stated attributes. Never an LLM's opinion. (*A verifier that asks a model "does this match?" inherits the model's unreliability.*)
2. **Every verdict records its evidence.** `AttributeCheck.evidence` says "page color field", "color in title/description", "title names a different neckline"... When something is wrong, you can see *why* without re-running anything, and users, support and evals can audit it.
3. **No evidence ⇒ `unknown`, never `match`.** Missing information is not agreement.
4. **Required vs optional attributes.** Price and item must match; colour must match or be explicitly *assumed*; fit, fabric, category and gender may be unknown, but **never mismatching**.
5. **Contradiction beats everything.** A stated colour that contradicts the request is always a rejection.
6. **Uncertainty is carried forward**, not hidden: `assumed=True` on the check, `confidence="low"` on the report and outfit, a lower rank, and a visible label for the shopper.

### Three-valued logic

Most code uses booleans. Verification of incomplete data needs **three** values:

| Status | Meaning | Example |
|---|---|---|
| `match` | evidence says yes | title contains "olive green" |
| `mismatch` | evidence says no | title says "black" when "olive green" was requested |
| `unknown` | no evidence either way | no colour mentioned anywhere |

Collapsing `unknown` into `match` ("probably fine") is how systems ship wrong results confidently; collapsing it into `mismatch` rejects most of the catalogue (only ~11% of titles state a colour, per the project's own measurement). The design choice here is the **middle path**: `unknown` on a required attribute is *allowed only if explicitly marked `assumed`* (the colour-specific search is evidence that the item is plausibly the requested colour), and anything assumed lowers confidence. That is **graded trust**.

### The data model

```python
class AttributeCheck(BaseModel):
    attribute: Literal["price", "category", "item", "color", "fit", "fabric", "gender"]
    requested: str
    found: str | None            # value read from the product data, "never invented"
    status: Literal["match", "mismatch", "unknown"]
    evidence: str | None         # the field or text the verdict is based on
    required: bool               # if True, anything but 'match' rejects the product
    assumed: bool = False        # trusted from the search query, not read from data

class MatchReport(BaseModel):
    is_match: bool
    confidence: Literal["high", "low"]
    score: float                 # share of checks that matched
    checks: list[AttributeCheck]
    blocking: list[str]          # attributes that caused rejection
```

The report is saved with each outfit item as JSONB (`outfit_items.verification`): **"the requested-vs-found comparison, kept as evidence"**. Storing the *reasoning* alongside the *result* is a core practice for auditable AI.

### Normalisation first

Matching free text needs normalisation (`_tokens`): lower-case; `t-shirt`/`t shirt` → `tshirt`; split on non-alphanumerics; drop stop words (`for, and, with, men, the...`); canonicalise variants through a dictionary (`tees → tshirt`, `trousers/pants → pant`, `jeans → jean`, `gray → grey`, `chinos → chino`). Plural/synonym folding is the cheapest accuracy gain in any keyword matcher.

### The checks, in order

**1. Price (required).** `price_inr <= spec.max_price_inr`. Pure arithmetic: mismatch if above.

**2. Item (required).** The wanted item words must all appear in the title/description tokens. Three outcomes:
* all present → `match`;
* some words missing, **but a garment noun is present** (`tshirt, shirt, polo, hoodie, pant, jean, chino...`) → `unknown + assumed` (right garment, title just does not repeat the descriptive words);
* a neckline conflict (asked crewneck, title says V-neck) → `mismatch`;
* otherwise → `mismatch` ("title/description lacks: ...").

Special cases encoded from real data: "crew neck" satisfies "crewneck"; stores call cargo trousers just "Cargos", which counts as pants (but never as shorts).

**3. Category (soft).** top vs bottom, from the page's category field or from garment words in the title. A product that looks like the *other* category is a mismatch.

**4. Colour (required).** An **evidence hierarchy**, each rung weaker than the one above:
1. page colour field (`attributes["color"]` or `product.color`) → match or mismatch;
2. colour words in title/description → `match`;
3. a *different* colour word in the title → `mismatch` (contradiction);
4. nothing stated → `unknown + assumed` (trusted from the colour-specific search).

**5. Gender (soft, but contradictions block).** Words like boys/girls/kids → mismatch; "unisex" or both men and women → match (unisex is acceptable for a male shopper); men → match; women → mismatch; nothing → unknown. The requested value is always `"men"`, because the app is menswear only.

**6. Fit and fabric (soft, only if requested).** Present → match. For fit there are **conflict groups** (`oversized/baggy/loose/relaxed/wide` vs `slim/skinny/fitted`): a conflicting word → mismatch. Otherwise unknown.

### The decision rule

```python
blocking = [
    c.attribute for c in checks
    if c.status == "mismatch" or (c.required and c.status != "match" and not c.assumed)
]
is_match   = not blocking
confidence = "low" if any(c.assumed for c in checks) else "high"
score      = round(matched / len(checks), 2)
```

Read it as two clauses: **(a) any mismatch blocks** (soft or required: a contradiction is a contradiction); **(b) a required attribute that is not a match blocks, unless it was explicitly assumed.** Clause (b) is a *safety net*: with today's checks, a required attribute can only come out as `match`, `mismatch`, or `unknown+assumed`, so clause (b) never fires; it exists so that **adding a new required check later fails safe** (rejects) instead of silently passing. Designing for the future developer is good engineering.

### Worked examples

Assume spec `(item, colour, cap)` and product title; results follow the code exactly.

| Spec | Product | Outcome | Why |
|---|---|---|---|
| t-shirt, white, oversized, ≤1500 | "Men's White Oversized Cotton T-Shirt", ₹799 | **match, high**, score 1.0 | every check has evidence |
| cargo pants, olive green, ≤2000 | "Men Black Cargo Pants", ₹1299 | **reject** (colour) | title names `black`, a different colour |
| jeans, blue, ≤2500 | "Women's Blue Skinny Jeans", ₹999 | **reject** (gender) | "women" ⇒ gender mismatch blocks, even though colour matches |
| chinos, beige, ≤2500 | "Slim Fit Chinos", ₹1199 | **match, low** | colour not stated anywhere ⇒ assumed |
| polo shirt, navy blue, ≤1500 | "Roadster Men Navy Blue Polo T-shirt", ₹999 | **match, low** | colour found as a phrase; but the item word "shirt" is not in the title (it says `tshirt`) while `polo` is ⇒ item `unknown+assumed` ⇒ confidence low |
| crewneck t-shirt, grey, ≤1000 | "Men V-Neck T-Shirt Grey", ₹499 | **reject** (item) | neckline conflict |
| any, any, ≤1000 | priced ₹1200 | **reject** (price) | arithmetic |

The fifth row is instructive: **the verifier is conservative about what it can prove**, and the confidence flag records *why* it is not certain. It also exposes a small mismatch between logic and UI: the badge text reads "Colour not confirmed" for *any* low-confidence outfit, but low confidence can also arise from a partially matched *item* description. A truthful label would name the actual assumed attribute (the `checks` list already says which). That is a real UX/accuracy improvement opportunity: *surface the evidence you already store.*

### Known limitations (an FDE should be able to list these)

* **Keyword matching, not understanding.** Synonyms outside the table ("tee", "tank", "kurti") can cause false rejections.
* **Colour words inside brand or product names** ("Red Tape", "Tan-line", "Black Coffee") can look like a contradictory colour and cause a **false rejection**. Mitigation: brand lists, using the structured colour field when present, or requiring colour words near garment nouns.
* **Multi-colour and pattern products** ("Navy/White Striped") are ambiguous.
* **Gender from text is approximate**: a title that says nothing is `unknown`, so some women's items with sparse titles can slip through as "not mismatching". A page-attribute source or a classifier would help, and it is a *soft* check by design.
* **Stale data**: prices and stock change; `fetched_at` exists on the product model for this reason; links are checked on demand at Buy time.
* **Only ~54% of results are usable** with assumed colour, so recall is limited by data, not by rules.

All of these are *measurable*: label a sample of products by hand and compute the verifier's precision and recall (Section 11.10).

## 11.4 `find_products_for_specs`: orchestrating search and verification

```python
def find_products_for_specs(inp: FindProductsInput, search: ProductSearch) -> FindProductsOutput:
    items = [s.top for s in specs] + [s.bottom for s in specs]
    def safe_search(spec):
        try:    return search(spec)
        except SearchUnavailable as exc:
            errors.append(str(exc)); return []                # one failure must not sink the rest
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(safe_search, items))           # all searches in parallel
    ...
```

Key behaviours:

* **Typed input and output** (`FindProductsInput`, `FindProductsOutput`) make it a clean unit with a contract; it never touches the database or HTTP.
* **Failure isolation**: a failed search becomes an empty list plus a shopper-safe error string; other items still proceed. Results return `search_errors` so the caller can decide (`after_validate` stops replanning when search is down).
* **Parallelism with a bound** (8 workers).
* **`_best_verified`**: verify each hit; reject with **explicit reasons** (`"color: asked 'olive green', found 'black' (mismatch)"`, `"availability: out of stock"`, `"duplicate: already used in another outfit"`); among survivors choose `max(key=(confidence == "high", score, price))`: confirmed first, then closer match, then the *higher* price (under the cap: "better quality for the money").
* **Dedup across outfits**: `used_urls` holds products already placed; **only reserved when an outfit is accepted**, so a half-filled spec does not hoard products.
* **Budget as a hard constraint**: an outfit exists only if `top.price + bottom.price <= budget`. The *reason* for failure is recorded precisely ("no verified match for 'peach chinos'" vs "verified items exceed the total budget together"). Those reasons become **planner notes**: the replanning prompt receives *feedback grounded in actual data*, which is far more effective than "try again".
* **Rejections returned** (`rejected`): visible for debugging and evaluation, never shown to shoppers. An AI system that cannot explain its rejections cannot be tuned.

The test data deserves a mention: `products.mock_search` returns three genuine matches plus **a decoy**: a wrong-colour product priced the highest, "so a search that skipped verification would pick it". **Design test data that makes the bug you fear observable**: if the verifier were removed, tests would fail by picking the decoy.

## 11.5 Other reliability tactics (generalised)

### Timeouts everywhere

Every network call needs a timeout; the default of "wait forever" turns a slow dependency into a hung system. In this repo: outbound HTTP `Timeout(20.0, connect=8.0)`; the MCP client `timeout=30`; token lifetimes 30 s; link check reads only 30 KB. Choose timeouts from the **latency budget** of the whole request (user patience ≈ 30-60 s for an agent turn), and make inner timeouts shorter than outer ones.

### Retries, correctly

* Retry only **transient** errors (timeouts, connection resets, 429, 5xx) and only **idempotent** operations.
* **Exponential backoff with jitter** and a cap (Chapter 4).
* **Bound** attempts; surface the final failure.
* **Do not retry at every layer.** If the HTTP client retries 3×, the tool retries 3×, and the agent retries 3×, one failure becomes 27 calls (a *retry storm*). In this repo retries are deliberately few and at known layers: provider calls (`retries=2`), MCP transport (`ATTEMPTS=2`), model output validation (`MODEL_ATTEMPTS=3`), replanning (`MAX_RETRIES=2`). Know your multiplication.

### Circuit breakers and bulkheads (not implemented here; know them)

A **circuit breaker** stops calling a dependency that is failing (closed → open after N failures → half-open probe → closed), protecting it and protecting you from piling up slow failures. A **bulkhead** limits resources per dependency (separate thread pools or concurrency limits) so one slow dependency cannot exhaust everything. The 8-worker pool and per-user limits are partial bulkheads. A production system serving real traffic would add a breaker around the search tool.

### Fallbacks and graceful degradation

When the primary path fails: use a **cached result**, a **cheaper/secondary model**, a **simplified answer**, or **say honestly that you cannot** (this app's `respond` tells the shopper the search is unavailable and to retry, rather than showing nothing or inventing results). Decide *in advance* which degradations are acceptable.

### Idempotency and exactly-once effects

Retries and resumes repeat work. Protect effects with idempotency keys, unique constraints and state checks (`UNIQUE (conversation_id, batch, position)`; the one-turn-at-a-time lock; interrupts placed in their own nodes).

### Backpressure and load shedding

Better to refuse quickly (429 with `Retry-After`) than to queue until everything times out. Rate limits per user, daily conversation caps and credit caps are load shedding with a *reason the caller can act on*.

### Timeouts for human steps

A paused conversation can wait forever; that is fine for storage but you need cleanup policies (expire stale pending interrupts, cap daily new conversations).

> *Diagnosing a specific hallucination (classify it, check whether the truth was in the context, vary one factor, fix the layer) is covered step by step in [Chapter 37, section 37.4](37-the-four-questions.md#374-why-is-the-model-hallucinating); this section is the catalogue of controls.*

## 11.6 Hallucination control: a pattern catalogue

| Pattern | How | Example here |
|---|---|---|
| **Ground in retrieved/tool data** | the model only talks about what it was given | the agent never asks the model to name products; products come from search |
| **Verify against sources** | deterministic check that claims appear in the data | `verify_product` |
| **Constrain the output space** | enums, schemas, allowed values | `Literal` categories; styles as a typed list |
| **Allow abstention** | nullable fields, "I don't know" paths | `PrefsExtraction` null; "colour not confirmed" |
| **Compute, do not recall** | code for arithmetic and lookups | totals, budget clamping |
| **Cite** | answers carry source ids/links users can open | product `url`, store name, price (from data) |
| **Cross-check with a second model** | an independent judge call | not used here (see Chapter 12 for judges); deterministic checks preferred |
| **Human in the loop** | approval where stakes are high | interrupts for missing facts and style choice |
| **Calibrate and label uncertainty** | show confidence to the user | `confidence` high/low badge |

## 11.7 Guardrails (input, output, action)

* **Input guardrails**: length limits (`text` is 1-500 characters; emails ≤ 254; passwords ≤ 128), `extra="forbid"` bodies, rate limits, content moderation, PII detection, language checks, prompt-injection heuristics (weak on their own).
* **Output guardrails**: schema validation, business-rule validation (budget, men's only), moderation/policy checks, link and URL allow-lists (`check_link`, `domain_allowed`), redaction of secrets.
* **Action guardrails**: least privilege, human confirmation for irreversible actions, limits on spend and volume, audit.

Tools and libraries exist (provider moderation endpoints, Llama Guard-style classifiers, NeMo Guardrails, Guardrails AI), but **deterministic code checks beat model-based guardrails wherever a rule can be stated precisely**, because they are testable, free, and cannot be talked out of it. Use model-based guardrails for fuzzy policies (toxicity, off-topic), and treat them as probabilistic.

## 11.8 A taxonomy of failures (and the honest message for each)

| Class | Example | System response | User message |
|---|---|---|---|
| **Transient** | timeout, 503 | bounded retry | "Please try again in a moment." |
| **Rate/quota** | 429, credit cap | refuse, `Retry-After`, no retry storm | "You have used today's search allowance." |
| **Permanent/config** | bad key, missing setting | fail fast, alert operators | generic apology; details in logs |
| **Logic/data** | no verified products | replan (bounded), then explain | "I couldn't find all 4 within your budget; try a higher budget or another style." |
| **Partial** | 3 of 4 outfits | deliver what is verified, say so | "...I could only find a few." |
| **Bug** | unexpected exception | log with trace id, audit, generic message | "Something went wrong on our side." |

Notice the principle: **never blame the user for our failures, never hide partial results as complete, never expose internals.**

## 11.9 Designing your own verifier: a recipe

1. **List the promises** your product makes ("every product is men's, within budget, in the colour requested").
2. **For each promise, define the evidence** that can support or refute it and *where it comes from* (structured field, text, external check). Rank the evidence by trust.
3. **Define the status values** (match/mismatch/unknown) and which attributes are required.
4. **Write the decision rule** as one small function with a comment for each clause.
5. **Normalise inputs** (case, punctuation, synonyms, units, currency).
6. **Record evidence** in the output.
7. **Choose conservative defaults**: when unsure, mark unknown/assumed and lower confidence, or reject.
8. **Write adversarial tests first**: decoys, near-misses, contradictions, empty fields, weird characters. Each bug found in production becomes a test.
9. **Measure** precision/recall on labelled data (11.10).
10. **Expose the evidence** to logs, evals and (where sensible) the UI.
11. **Re-check at the last gate** before the user sees anything (`rank_and_validate`).

## 11.10 Measuring the verifier itself

A verifier is a classifier, so evaluate it like one (Chapter 5):

* Label ~200 real (spec, product) pairs as truly matching or not.
* Compute **precision** (of products it accepted, how many truly match? **this is the number that protects users**) and **recall** (of truly matching products, how many did it accept? this drives how often you can fill four outfits).
* Break down by attribute (colour errors vs item errors vs gender errors) to find which rule to improve.
* Track `OUTFIT_CONFIDENCE` (high vs low outfits) in Prometheus: a falling share of `high` after a data or provider change signals the data got sparser.
* Run the **evals** with decoys and with real data; the *colour-confirmed share* scorer is informational because low there is "honest, not wrong".

Project data points worth quoting in an interview: colour is stated in ~11% of search titles; the assumed-colour fallback makes ~54% of results usable. These numbers shaped the design (the verifier would be useless if it demanded confirmed colours), a good example of **data-driven rule design**.

## Common mistakes

* Letting the model be the verifier of its own output.
* Collapsing "unknown" into "yes".
* Silent failures: swallowing exceptions or returning empty results without saying why.
* Retrying at every layer.
* No timeouts.
* Hiding uncertainty from users (a label costs nothing and builds trust).
* Over-strict rules that reject everything (a verifier that never passes is a broken product).
* No test data that would expose the failure you fear.

## Summary

* Make the system trustworthy around the model: constrain, validate, enforce, verify, re-check, degrade honestly.
* A good verifier is deterministic, evidence-based, three-valued, conservative on required attributes, explicit about assumptions, and tested with decoys.
* Orchestration code isolates failures, runs work in parallel with bounds, records rejection reasons, and feeds grounded notes back to the planner.
* Reliability engineering also means bounded retries, timeouts, backpressure, idempotency, fallbacks, and honest messages.
* Measure the verifier as a classifier and surface the evidence you already store.

## Key terms

*grounding, verification, three-valued logic, evidence, assumed attribute, confidence, blocking, graceful degradation, circuit breaker, bulkhead, retry storm, idempotency key, guardrail, decoy test, precision/recall.*

## Interview questions

1. How do you make an LLM-powered feature trustworthy? Give the layers.
2. Why three-valued logic for verification? What goes wrong with booleans?
3. Walk me through how `verify_product` decides colour. Which parts are most fragile?
4. What is a retry storm and how does this system avoid it?
5. How would you evaluate the verifier? Which metric matters most to users?
6. What does "fail closed" mean here? Give two examples.
7. When would you use a model as a verifier instead of code?
8. How should uncertainty be shown to users?

## Exercises

1. Add a test with a product titled "Red Tape Men's Navy Shirt" requested as "navy shirt". Predict the outcome, run it, then design a fix that does not break other tests.
2. Change the "Colour not confirmed" badge to name the assumed attribute (colour vs item), using `verification.checks`. Update `types.ts` and `OutfitCard.tsx`.
3. Add a circuit breaker around `McpProductSearch` (open after 3 consecutive failures for 30 s) with tests using a fake clock.
4. Hand-label 50 products from a live search for "olive green t-shirt" and compute verifier precision and recall.
5. Implement the optimal assignment of products to outfits (Hungarian algorithm) and compare to the greedy result on mock data; discuss whether the added complexity is worth it.
