# Chapter 29. Testing

> **Learning objectives.** Design a test strategy (the pyramid and what belongs at each level); write clear, deterministic, isolated tests with pytest and Vitest; use fakes, recorded fixtures, fake clocks and real throwaway databases effectively; apply property-based testing, contract tests and security tests; test AI components without a real model; and read this repo's roughly 224 Python tests and TypeScript tests as a worked example of good practice.
>
> **Prerequisites.** Chapters 2, 9, 11, 12.

---

## 29.1 Why test, and what tests are for

Tests do four jobs: **(1) catch regressions** (a change broke something that worked), **(2) document behaviour** (a test named `test_a_token_holds_no_secret_material` states a requirement better than a comment), **(3) enable refactoring and upgrades** (you can swap a library or model and know), and **(4) shape design** (code that is easy to test is usually decoupled; Chapter 2's dependency injection).

For AI systems tests matter *more*, not less: the model is unreliable, so the deterministic code around it must be **provably right** (budget clamping, verification, auth, limits, parsing), and the model itself needs **evals** (Chapter 12), which are tests for probabilistic behaviour.

### The test pyramid

```
            /\        few    END-TO-END (browser through the real stack)       slow, brittle, high confidence
           /  \
          /----\      some   INTEGRATION (real DB, HTTP surface, fake externals) medium
         /      \
        /--------\    many   UNIT (pure functions, small classes)               fast, precise
       ------------
        + EVALS (AI behaviour) + SECURITY tests + CONTRACT tests + PERFORMANCE tests alongside
```

* **Unit tests**: one function or class, no I/O. Milliseconds. `verify_product`, `clamp_to_budget`, `SlidingWindow`, `canonicalize`.
* **Integration tests**: several pieces together with a **real** dependency where it matters: the API with a real Postgres.
* **End-to-end tests**: a real browser drives a real deployment. Few, covering critical journeys.
* **The "ice-cream cone" anti-pattern** (mostly slow end-to-end tests, few unit tests) gives slow, flaky, hard-to-diagnose suites.

Other kinds: **contract tests** (the interface between components: the tool-contract test), **property-based tests**, **snapshot tests**, **mutation tests** (do your tests notice when the code is broken on purpose?), **load/performance tests**, **accessibility tests**, **security tests**, **evals**.

## 29.2 Qualities of a good test

* **Fast** (so it is run constantly), **deterministic** (same result every time), **isolated** (no dependence on order or shared state), **readable** (the name and body explain the requirement), **focused** (one behaviour per test), **maintainable** (does not break when internals change but behaviour does not).
* **Arrange - Act - Assert** structure; **test behaviour, not implementation**.
* **Test names as specifications.** Examples from this repo:
  * `test_replaying_an_already_used_refresh_token_revokes_the_whole_family`
  * `test_a_hostile_dns_that_changes_its_answer_cannot_redirect_us_to_an_internal_address`
  * `test_buy_link_refuses_products_the_user_was_never_shown_so_credits_cannot_be_drained`
  A failing name tells you *which promise broke* without opening the file.
* **Test the sad paths** as seriously as the happy path: invalid input, timeouts, refusals, concurrency, partial failure.
* **Boundary values**: 0, 1, limit, limit+1, empty, very large, unicode (`₹`), negative.
* **No logic in tests** (loops/conditionals that could themselves be wrong).
* **Do not test the framework or the library**; test *your* use of it.
* **A test you have never seen fail proves nothing.** Break the code on purpose to confirm it fails (or write the test first).

## 29.3 Test doubles: what to fake and what to keep real

| Double | What it is | Use |
|---|---|---|
| **Stub** | returns canned answers | simple dependency replacement |
| **Fake** | a working, simplified implementation | an in-memory checkpointer (`MemorySaver`), `ScriptedLLM`, `mock_search`, `FakeTools` |
| **Mock/spy** | records calls so you can assert on them | "was the provider called?" (`test_the_refused_search_never_reaches_the_provider`) |
| **Recorded fixture** | real captured data replayed | `tests/fixtures/serpapi_*.json`: real SerpAPI responses |

**Guidance**

* **Fake at the boundaries of your system** (network, model, clock, filesystem), **not inside it**. Over-mocking your own code makes tests that pass while the real code is broken.
* **Prefer fakes and recorded real data over hand-written mocks**: a fake that behaves like the real thing catches integration bugs; a mock only checks that you called it the way you *thought* you should.
* **Keep the database real** when SQL, constraints, triggers, locks or transactions matter. This repo's API tests use a **real Postgres** (a fresh migrated database per test; Section 29.5). Mocking a database for SQL-heavy code produces tests that cannot fail where it counts.
* **Inject time and randomness**: `clock=` parameters on `SlidingWindow`, `RateLimiter`, `CreditLedger`, `ReplayGuard`; `now=` on token minting. Tests advance a fake clock instead of sleeping (no flakiness, no slowness).
* **Fake the model**: the LLM is non-deterministic, slow and expensive. The repo has two fakes: `ScriptedLLM` (deterministic scripted answers, also used for demo mode) and a test `FakeLLM`. They prove the **plumbing** (graph flow, validation, persistence, streaming) and **never** model quality (Chapter 12).
* **Decoys in test data**: `mock_search` includes a wrong-colour product priced highest, so a verifier bug would pick it and fail `test_find_products_never_returns_the_wrong_colour_decoy`.

## 29.4 pytest in practice

```python
# fixtures: reusable setup/teardown; `yield` marks the boundary
@pytest.fixture
def pool(db_url):
    p = make_pool(db_url, min_size=1, max_size=8)
    yield p                       # the test runs here
    p.close()                     # teardown always runs

# factory fixture: returns a function so a test can create several resources
@pytest.fixture
def make_database():
    created = []
    def factory() -> str: ...
    yield factory
    ...drop every database created...

# parametrisation: one test body, many inputs
@pytest.mark.parametrize("text,budget", [("around 4000 rupees", 4000), ("₹4,000", 4000), ("under 4k", 4000)])
def test_budgets_are_read_from_natural_phrases(text, budget):
    assert parse_budget(text) == budget

# expecting errors
with pytest.raises(RuntimeError, match="MCP_JWT_PRIVATE_KEY"):
    ServiceTokenAuth("u", Settings(mcp_jwt_private_key="", _env_file=None))

# skipping when an external dependency is absent
pytest.skip("Postgres is not running (docker compose up -d postgres)")
```

Concepts: **fixtures** (scope: function, module, session; `conftest.py` shares them), **parametrize**, **marks**, **monkeypatch** (temporarily change env vars/attributes), **`tmp_path`**, **assert rewriting** (readable failure diffs), **`-k`** (select by name), **`-x`** (stop at first failure), **`-q`**, `--lf` (last failed). `Settings(..., _env_file=None)` in tests prevents the developer's real `.env` from leaking into test behaviour: *tests must not depend on the machine they run on.*

### A real database per test

`tests/conftest.py`:

```python
name = f"stylist_test_{uuid.uuid4().hex[:10]}"
admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))       # identifier-safe SQL composition
url = _url_for(name); migrate(url)                                              # tests the migrations from scratch
...
admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
```

Benefits: perfect isolation (parallel-safe), proof that migrations apply cleanly, real triggers/constraints/locks. Cost: needs Postgres (a few hundred ms per test for creation); the tests **skip** if it is not reachable (convenient locally; in CI make skipping a failure so a broken service does not silently turn the suite green: Chapter 28).

## 29.5 What each suite proves (from the test names)

### API (`services/api/tests`): ~146 test functions

| File | What it proves |
|---|---|
| `test_verify.py` (27) | the verifier: genuine matches carry evidence; wrong colour rejected from the page field and from the title; **unstated colour trusted but flagged low confidence**; contradiction still rejected under the fallback; confirmed outranks low-confidence even if cheaper; price cap; category and fit conflicts; synonyms (tee/trousers/cargos/shirt); neckline conflict; right garment with a missing descriptive word accepted as low confidence; **the wrong-colour decoy is never returned**; a hallucinated search result is rejected; men's/unisex/unstated accepted, women's/kids' rejected; duplicates and `exclude_urls`; out-of-stock; budget across the outfit |
| `test_agent.py` (12) | the graph: full flow pauses for missing info then style choice; **gender is never asked** (menswear-only decision as a test); state survives between calls via the checkpointer; empty search retries then gives up; retry asks only for missing outfits; `clamp_to_budget`; LLM factory endpoint selection, model ids with slashes/colons, missing key/unknown provider; schema tolerance for "None"/amount formats; bad model answers retried then succeed or raise |
| `test_accounts.py` (23) | passwords (policy, hashed, salted, timing of missing accounts), access tokens (round trip, 15-minute life, refusals, **a service token cannot log in**), refresh tokens (random, hash only, single exchange, **replay revokes the family**, other logins unaffected, unknown/expired/disabled), sliding window, lockout rules, registration/auth edge cases, logout |
| `test_database.py` (12) | migrations apply and are idempotent; case-insensitive email uniqueness; email shape check; outfit rules enforced by the database; cascade delete of a user's data; **audit chain: linked, reproducible, triggers refuse update/delete/truncate, tampering detected even with triggers bypassed, deletion detected, "rewrite entry and its hash" still breaks the next link, many concurrent writers keep one chain** |
| `test_http.py` (31) | the whole HTTP surface (below) |
| `test_mcp_search.py` (9) | the client side of the tool server: result → `Product`; arguments sent; empty results; refusals carry messages; unreachable server never leaks detail; **parallel searches in threads**; search outage gives a clear message and **no endless replanning**; partial failure still builds what it can |
| `test_mcp_auth.py` (8) | the API signs correct tokens (claims, lifetime, unique `jti`, no secret material, public key cannot sign, a new token per HTTP request, one-line PEM keys, refuses without a private key) |
| `test_telemetry.py` (20) | trace-id adoption and rejection, request/trace ids on responses and audit entries, per-step timings, waiting-for-user outcome, model wrapper counting, metrics gating/authorisation/templated routes, JSON logs without sensitive data, exceptions logged as one JSON line, **demo-mode** budget parsing, scripted model behaviour, a full demo conversation through the real checkpointer, **demo refused in prod** |
| `test_repo_hygiene.py` (3) | no secrets in `.env.example`; no key-shaped strings in committable files; `.env` ignored |
| `test_health.py` (1) | liveness |

`test_http.py` is the capstone: register/cookie attributes; bad signups; conflicts; identical answers for wrong password vs unknown email; lockout; refresh needs CSRF header and rotates; **replayed refresh cookie logs everyone out and is recorded**; logout; protected endpoints refuse bad tokens; expired and service tokens refused; security headers + request id; **CORS only for our origin**; audit events without secrets and chain verifies; admin-only verify (404 for others); **users see only their own conversations**; a full streamed conversation (progress, questions, outfits); evidence saved per item; **audit records that messages were sent, never what they said**; empty/blank/oversized messages refused; rate limits; **a second message during a running turn is refused, not interleaved**; daily conversation cap; **agent crash gives a clean message and the conversation is not stuck**; rate-limited model gives a friendly "busy"; new request after finishing starts a fresh round; buy link resolves only shown products and checks them; **credits cannot be drained** by unseen product ids; buy link rate-limited and requires login; tool-server limit → 503 and outage → 502; **a dead store link is reported, not hidden**.

### Tool server (`services/mcp/tests`): ~78 test functions

* `test_auth.py` (22): valid/forged/edited/long-lived tokens, clock tolerance and leeway semantics, skew logging, **single-use** (works once, replay refused even before expiry, forgotten after it could no longer be valid), no token, replay over real HTTP, per-request tokens, foreign Host/Origin refused, **refuses to start without a usable public key**, one-line PEM.
* `test_check_link.py` (18): verdict mapping, soft-404, timeout is *unverified not dead*, redirects within/outside the allow-list, redirect loops, https only, allow-list, **private-address resolution refused**, lookalike hostnames, **connection goes to the checked IP with the real name for Host/TLS**, **hostile DNS cannot redirect to an internal address**, each hop re-checked, pinning for IPv4/IPv6/ports, non-200 2xx not proof of life.
* `test_limits.py` (13): per-user rate limit with retry hint, sliding window, isolation between users, daily allowance and global cap, refused spends not counted, UTC midnight reset, HTTP-level enforcement, **cached searches are free and refused ones never reach the provider**, `/health` needs no login, refuses to listen beyond loopback without allowed hosts.
* `test_search_products.py` (13): parse **real saved responses**, list price from discounts, query always says "men" and dedupes words, unknown retailers dropped with warnings, price cap and limit, cache, 429 retry, bad key fails immediately, gives up after retries, no key refuses to call out, discoverable through MCP, **schema rejects invalid args before our code runs**, provider outage → clean tool error.
* `test_buy_link.py` (4), `test_metrics.py` (7: **the metrics text holds no user ids, arguments or product data**), `test_tool_contract.py` (1: every tool is well-formed and returns both forms).

### TypeScript

* **Web** `sse.test.ts`: parser edge cases (split chunks, CRLF, split `₹` bytes, missing trailing blank line, corrupt blocks skipped).
* **Mastra** `chain.test.ts` (canonicalisation, linking, concurrent appends, a failed append does not stop later ones, tampering variants including "entry rewritten with its own hash" and "last entry replaced", persistence across restart), `rules.test.ts` (every scorer, including edge cases), `report.test.ts` (**the pass/fail gate can really fail**: each hard guarantee has a failing case; soft signals do not fail the run; the dataset has unique ids, answers for every expected question, covers complete/partial/empty), `session.test.ts` (the simulated shopper, `StylistApi` with 429 retry, capped `Retry-After`, traceparent, chunk-split SSE).

*Note `report.test.ts`: it is a test of a test harness: "the pass/fail gate can really fail" is exactly the "test your tests" principle from Chapter 12.*

## 29.6 Property-based testing

Instead of examples, state a **property** that must hold for *all* inputs; the library generates many inputs, finds a failing one and **shrinks** it to a minimal counter-example. Python: **Hypothesis**; JS: **fast-check**.

```python
from hypothesis import given, strategies as st
from api.agent.graph import clamp_to_budget
from api.agent.schemas import ItemSpec, OutfitSpec

item = lambda cat: st.builds(ItemSpec, category=st.just(cat), item=st.just("x"), color=st.just("blue"),
                             max_price_inr=st.integers(min_value=1, max_value=100_000))

@given(top=item("top"), bottom=item("bottom"), budget=st.integers(min_value=1, max_value=200_000))
def test_clamped_caps_never_exceed_the_budget(top, bottom, budget):
    spec = OutfitSpec(top=top, bottom=bottom, rationale="r")
    out = clamp_to_budget(spec, budget)
    assert out.top.max_price_inr + out.bottom.max_price_inr <= budget
```

(One subtlety this would surface: `clamp_to_budget` truncates caps with `int(...)`; with a tiny budget a cap can become `0`, and a spec with `max_price_inr` 0 is a degenerate search. A property test finds such corners that example tests miss.) Good properties: round trips (`parse(format(x)) == x`), idempotence (`clamp(clamp(x)) == clamp(x)`), invariants (budget never exceeded, no duplicates), "never crashes" fuzzing on parsers (`parseBlock`, `_tokens`, `parse_budget`).

## 29.7 Testing specific kinds of code

* **Web handlers**: through `TestClient` (in-process ASGI), asserting status, headers, body, and **side effects in the database** (audit rows, saved outfits).
* **Streaming**: collect the whole body and parse events (`events(response)` helper), assert **event order** (`status…`, `interrupt`/`outfits`, `done`), and assert that an error still ends with `done`.
* **Concurrency**: use threads to hammer a function and assert invariants (the audit chain test with many writers); control interleavings with barriers or fake clocks; remember that absence of a failure in a race test is weak evidence (run many iterations).
* **Time-dependent code**: fake clock injection.
* **External HTTP**: recorded fixtures; `httpx.MockTransport` (used with `httpx2` in `test_mcp_auth.py`: a handler function stands in for the network); **never call real services in unit tests**.
* **Security properties** (as ordinary tests): negative tests for every access-control rule, SSRF attack strings, token tampering, rate limits, no secrets in logs/metrics/audit.
* **CLI/scripts**: run against temp directories; assert files and exit codes; scripts that touch `.env` (the key generator) should have tests using a temporary path argument.
* **Migrations**: apply from scratch and from the previous version with data.
* **LLM-dependent code**: fakes for unit/integration; **evals** for behaviour; **contract tests** that the structured-output schema and prompt placeholders are consistent (a test that loads each prompt and renders its context, or validates that every prompt file referenced in code exists).
* **Front end**: Vitest for logic, React Testing Library for components, Playwright for journeys (this project verified the UI end to end in a real browser via Playwright), axe for accessibility.

## 29.8 Mutation testing, coverage and quality metrics

* **Coverage** (pytest-cov / c8): which lines/branches ran. **Useful for finding untested code; a poor measure of test quality** (a test with no assertions gives 100% coverage). Target meaningful branches (error paths), not a vanity number.
* **Mutation testing** (mutmut, Stryker): automatically introduce small bugs (`<` to `<=`, delete a line) and check that a test fails; surviving mutants reveal weak tests. Slow; apply to critical modules (the verifier, token checks, limits).
* **Flakiness rate**, **suite duration**, **time to diagnose a failure** are quality metrics for the suite itself.

## 29.9 Test-driven development and design

**TDD**: write a failing test, make it pass with the simplest code, refactor. Benefits: designs for testability, a safety net, small steps. It is particularly effective for **bug fixes** ("reproduce as a failing test first") and for **pure logic** (parsers, validators, scoring rules). The project's discipline of writing the failing case first for each security rule shows in the test names.

Design for testability (Chapter 2): **inject dependencies**, separate **pure logic** from **I/O**, pass **clocks and random sources**, expose **seams** (`ProductSearch` callable; `graph_factory`; `tool_client_factory`; `build_server(provider=, http_client=, resolver=)`).

## 29.10 AI-specific testing summary

| Concern | Technique |
|---|---|
| Deterministic wrappers around the model (validation, retries, parsing) | unit tests with scripted fake models |
| Agent flow, persistence, interrupts | graph tests with `MemorySaver` and fakes; full-stack tests with real Postgres checkpointer in demo mode |
| Verification/guardrails | exhaustive example tests + decoys + property tests |
| Tool server contracts | contract test over every tool; schema rejection tests |
| Prompt changes | evals with before/after comparison (Chapter 12) |
| Model behaviour | live evals, LLM-judge calibrated on human labels |
| Safety | red-team/attack suites, injection strings in every input channel |
| Cost/latency regressions | per-run call counts and timing scorers (`callEfficiency`, `latency`); load tests in demo mode |

## Common mistakes

* Mocking everything so tests pass regardless of reality.
* Sleeping in tests instead of injecting a clock.
* Tests that depend on order, shared state, the network, or the developer's `.env`.
* Asserting implementation details (private method calls) rather than behaviour.
* Chasing coverage numbers; assertion-free tests.
* Silent skips in CI.
* Only happy-path tests; no negative or security tests.
* Flaky tests tolerated.
* Calling real paid APIs in tests.
* Never seeing a new test fail.

## Summary

* Use the test pyramid plus evals, contract, property, security and performance tests; keep most tests fast and deterministic.
* Fake the boundaries (network, model, time), keep your own code and your **database real** where SQL semantics matter; use recorded real data as fixtures.
* Name tests as specifications; test sad paths, boundaries and security properties.
* This repo's ~224 Python tests and TypeScript tests cover verification, agent flow, accounts and tokens, database constraints and audit tamper-detection, the HTTP API end to end, tool-server auth/SSRF/limits/metrics privacy, parser edge cases, and even test the eval gate itself.
* Property-based and mutation testing find what examples miss; coverage is a flashlight, not a goal.

## Key terms

*unit/integration/end-to-end test, test pyramid, fixture, parametrisation, stub/fake/mock, recorded fixture, dependency injection, fake clock, property-based test, shrinking, mutation testing, coverage, flaky test, contract test, snapshot test, TDD, eval.*

## Interview questions

1. Describe the test pyramid. Where do AI evals fit?
2. When should a test use a real database instead of a mock? Why does this repo create a database per test?
3. How do you test code that depends on time? On a model?
4. What is a fake versus a mock? Give an example from this repo.
5. What makes a test flaky and how do you fix it?
6. How would you test that user A cannot read user B's conversation?
7. What is property-based testing? Write a property for `clamp_to_budget`.
8. What do coverage and mutation testing tell you, and what do they not?

## Exercises

1. Add the Hypothesis test from 29.6; see if it finds the zero-cap corner; decide the right behaviour and fix with a test first.
2. Add a mutation-testing run (mutmut) on `verify.py`; list surviving mutants and add tests to kill them.
3. Write a test proving each public route either requires auth or is in an explicit allow-list (a guard against forgetting the dependency).
4. Write a Playwright test for register → chat (demo mode) → style card → outfits → Buy (mock link) and run it in CI.
5. Make skipped Postgres tests fail when `CI=true`.
6. Add a regression test for the "Red Tape Men's Navy Shirt" colour-in-brand case from Chapter 11, fix the verifier, and confirm no other test breaks.
