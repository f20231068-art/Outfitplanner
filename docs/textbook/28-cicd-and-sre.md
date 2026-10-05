# Chapter 28. CI/CD and Site Reliability

> **Learning objectives.** Explain continuous integration and delivery and design a pipeline; write a GitHub Actions workflow for this monorepo (tests with a real Postgres, type checks, image builds, scans, offline evals, gated deploy); choose a deployment strategy (rolling, blue/green, canary, feature flags) and handle migrations and rollbacks; apply infrastructure as code; and practise SRE habits (SLOs, incidents, postmortems, load and chaos testing). Includes AI-specific release concerns: prompts, models and evals as part of delivery.
>
> **Prerequisites.** Chapters 12, 13, 24-27.

---

## 28.1 What CI/CD is for

* **Continuous Integration (CI)**: every change is automatically **built and tested** in a clean environment, many times a day, so integration problems surface in minutes, not weeks.
* **Continuous Delivery**: every change that passes CI is **releasable**; deploying is a button (or a merge).
* **Continuous Deployment**: passing changes deploy to production **automatically**.

The payoff is measured by the four **DORA metrics**: **deployment frequency**, **lead time for changes**, **change failure rate**, **time to restore service**. High performers deploy often in small batches *and* have lower failure rates: small changes are easier to review, test, and roll back.

### The pipeline as a funnel

```
commit → [fast checks: lint, types, unit tests]  (seconds-minutes)
       → [integration: real Postgres, API tests, builds]  (minutes)
       → [offline evals, security scans, image build]      (minutes)
       → artifact (image tagged with the commit SHA)
       → deploy to staging → smoke tests → (approval) → production → post-deploy checks & monitoring
```

Principles:

1. **Fast feedback first**: cheap checks before expensive ones; fail early.
2. **Build once, deploy the same artifact everywhere** (promote the image tagged `<sha>`; do not rebuild per environment).
3. **Automate everything repeatable**, **version everything** (code, config, infrastructure).
4. **Keep `main` always releasable**; a red `main` stops the line.
5. **Make the pipeline the only way to production** (no manual `scp`).
6. **Secrets stay out of the repo**; CI gets short-lived credentials (OIDC) or masked secrets.
7. **Reproducibility**: lockfiles, pinned base images/actions, containers for CI jobs.

## 28.2 A GitHub Actions workflow for this repo

This repo has no committed pipeline yet (`.github/workflows/` is absent). Here is a realistic one. **Adapt it, and pin every third-party action to a full commit SHA in real use** (tags can be moved; compromised actions are a known supply-chain attack).

```yaml
# .github/workflows/ci.yml
name: ci
on:
  pull_request:
  push: { branches: [main] }

permissions: { contents: read }          # least privilege for the default token

concurrency:                              # cancel superseded runs on the same branch
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  api:
    runs-on: ubuntu-latest
    services:
      postgres:                           # a REAL database, as the tests expect (they create throwaway DBs)
        image: postgres:17
        env: { POSTGRES_USER: stylist, POSTGRES_PASSWORD: stylist_dev_password, POSTGRES_DB: stylist }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U stylist" --health-interval 5s --health-timeout 3s --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5       # installs uv with caching
      - run: uv sync --frozen
        working-directory: services/api
      - run: uv run ruff check .
        working-directory: services/api
      - run: uv run pytest -q
        working-directory: services/api

  mcp:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --frozen && uv run ruff check . && uv run pytest -q
        working-directory: services/mcp

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm }
      - run: npm ci
      - run: npm run typecheck -w apps/web
      - run: npm test -w apps/web
      - run: npm run build -w apps/web
      - run: npm test -w apps/mastra
      - run: npx tsc --noEmit
        working-directory: apps/mastra

  evals-demo:                              # the free, offline pipeline eval (Chapter 12): gates fail the build
    needs: [api, web]
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env: { POSTGRES_USER: stylist, POSTGRES_PASSWORD: stylist_dev_password, POSTGRES_DB: stylist }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U stylist" --health-interval 5s --health-timeout 3s --health-retries 10
    env: { BACKEND_MODE: demo, ENVIRONMENT: dev }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: npm }
      - run: uv run --project services/mcp python scripts/generate_jwt_keys.py     # writes throwaway keys into .env (never printed)
      - run: npm ci
      - name: start API in demo mode
        run: |
          (cd services/api && uv sync --frozen && nohup uv run uvicorn api.main:app --port 8000 > /tmp/api.log 2>&1 &)
          for i in $(seq 1 30); do curl -sf localhost:8000/health && break || sleep 2; done
      - run: npm run eval -- --concurrency 2        # exit code 1 if any hard guarantee fails
      - if: failure()
        run: tail -n 100 /tmp/api.log

  images:
    needs: [api, mcp, web]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: build (no push) with cache
        run: |
          docker buildx build -f services/api/Dockerfile -t stylist-api:${{ github.sha }} --load .
          docker buildx build -t stylist-mcp:${{ github.sha }} --load services/mcp
          docker buildx build -f apps/web/Dockerfile -t stylist-web:${{ github.sha }} --load .
      - name: scan images (fail on HIGH/CRITICAL with a fix available)
        uses: aquasecurity/trivy-action@0.28.0
        with: { image-ref: "stylist-api:${{ github.sha }}", severity: "HIGH,CRITICAL", ignore-unfixed: true, exit-code: "1" }
      # repeat for the other images, then on main: log in to GHCR and push the same tags (build once, deploy the same artifact)
```

What this encodes:

* **Real Postgres service container** matching the defaults in `config.py`, because the API tests create and drop throwaway databases and test triggers, locks and constraints for real (they **skip** if Postgres is absent, which would silently hide failures: in CI make sure the service is up, or make "skipped" a failure for CI).
* **`--frozen`/`npm ci`**: fail if lockfiles drift.
* **Ruff + pytest** exactly as the README lists; **typecheck + vitest + build** for the web; **Mastra** tests and type-check.
* **A demo-mode eval job**: boots the real API against Postgres with the scripted model and mock search, runs the 13-case eval, and **fails the pipeline on any gate failure** (exit code 1). The key-generation step uses the repo's script to create **throwaway** keys in an ephemeral `.env`, never printed.
* **Image builds** for all three Dockerfiles (the API and web builds use the repo root as context) and a **vulnerability scan**.
* **Concurrency control** and **least-privilege `permissions`**.

### Pipeline hardening

* **Pin actions by SHA**; use Dependabot to update them.
* **`pull_request_target` and secrets**: workflows triggered by forks must not run untrusted code with secrets. Use plain `pull_request` for tests; keep secrets only on trusted branches/environments.
* **OIDC to the cloud**: GitHub issues a short-lived token your cloud trusts (workload identity federation), so no long-lived cloud keys live in repository secrets.
* **Environments with required reviewers** for production deploy jobs; **protected branches** requiring status checks.
* **Secret scanning and push protection** enabled; hygiene tests (the repo's `test_repo_hygiene.py` runs in the `api` job).
* **Cache dependencies** (uv/npm/BuildKit) for speed, but never cache secrets.
* **Artifacts**: upload eval reports and logs on failure.
* **Path filters** to skip unrelated jobs in the monorepo (`on.push.paths`, or a changed-files action).

## 28.3 Testing strategy inside CI

The **test pyramid**: many fast **unit** tests, fewer **integration** tests (real DB, real HTTP surface with fake external services), few **end-to-end** tests (browser), plus **evals** for AI behaviour (Chapter 29 expands).

* **Flaky tests are bugs**: quarantine and fix; never "rerun until green".
* **Make skips visible**: a test that skips when Postgres is down must fail in CI.
* **Test the pipeline's own safety**: a known-bad change should turn it red.
* **Run time budgets**: keep PR feedback under ~10 minutes (split jobs, parallelise, cache).
* **Live-model evals** (cost, quota, non-determinism) belong in a **scheduled** job with budgets and alerts, not on every PR; run a **small smoke subset** on release candidates.

## 28.4 Deployment strategies

| Strategy | How | Pros | Cons |
|---|---|---|---|
| **Recreate** | stop old, start new | simple; **what Compose does** | downtime |
| **Rolling** | replace instances gradually | no downtime, little extra capacity | two versions run at once (schema/API compatibility needed) |
| **Blue/green** | run a full new stack ("green"), switch traffic, keep "blue" for rollback | instant rollback | double capacity; state/migrations tricky |
| **Canary** | send 1-5% of traffic to the new version, watch metrics, ramp up | limits blast radius; real-traffic validation | needs good metrics and routing |
| **Shadow/mirroring** | send copies of traffic to the new version, discard responses | zero-risk comparison | extra load; side effects must be avoided |
| **Feature flags** | ship code dark; enable per user/percent at runtime | decouple deploy from release; instant kill switch | flag debt; testing combinations |

For a Compose-on-VM deployment you can approximate blue/green: run the new stack under a different project name on other ports, test it, switch Caddy's upstream, then stop the old one.

### Database migrations and deploys

Old and new code **overlap in time**, so migrations must be **backward compatible** (expand → migrate → contract; Chapter 17): add a nullable column first; deploy code that handles both; backfill; later remove the old column. **Never** deploy a migration that breaks the currently running code. Code can be rolled back; **data changes mostly cannot**, so test migrations on a restored production copy and take a backup first.

### Rollback

* **Application**: redeploy the previous image tag (SHA). Keep the last N images available.
* **Configuration**: configuration changes are deployments too; keep them in git.
* **Data**: restore from backup/PITR (slow, lossy): avoid needing it with expand/contract and feature flags.
* **Practise rollbacks**; an untested rollback is a hope.

### Release checklist (this app)

- [ ] CI green on the commit to release (tests, evals, scans).
- [ ] Image tags = commit SHA; changelog entry.
- [ ] Migrations reviewed (backward compatible); backup taken.
- [ ] Config/secrets changes applied (`.env.production` updated; rotated keys planned).
- [ ] Deploy to staging (or the laptop prod-layout) and run: `/health`, register, demo chat, buy link, audit verify.
- [ ] Deploy; watch dashboards and logs for 15 minutes (error rate, p95 turn time, rate-limit and credit metrics).
- [ ] Post-deploy smoke test (a live eval case if budget allows).
- [ ] Announce; update the runbook and docs.

## 28.5 AI-specific delivery concerns

A deployment of an AI product has *more moving parts than code*:

| Artefact | Treat it as | Practice |
|---|---|---|
| **Prompts** | code (they are versioned files: `prompts/stylist/*.vN.md`) | PR review, evals before/after, the version is **pinned in code** (`load_prompt("plan_outfits", 2)`), rollback = change one number |
| **Model choice/version** | configuration (`STYLIST_MODEL`) | change via env, canary it, keep a fallback, pin versions where the vendor allows, **re-run evals on every change** |
| **Schemas/contracts** | API (Pydantic models, tool schemas with `schema_version`) | versioning and compatibility tests (tool-contract test) |
| **Retrieval indexes/embeddings** | data | version the embedding model; blue/green re-indexing; rollback by switching index alias |
| **Eval datasets** | code | in git; new failures become cases |
| **Provider behaviour** | an external dependency that can change under you | scheduled live evals and synthetic checks; alert on quality regressions |

**Eval gates in CI/CD**: offline deterministic evals as blocking checks; live evals scheduled; **quality canaries** (small traffic share on a new prompt/model with outcome metrics such as outfit delivery rate, no-outfit rate, Buy-click rate, error rate, cost per conversation) and automatic rollback criteria.

## 28.6 Infrastructure as Code and GitOps

**IaC** describes infrastructure declaratively so it is reviewable, repeatable and recoverable.

* **Terraform/OpenTofu**: providers (AWS, GCP, Cloudflare...), **resources**, **variables/outputs**, **modules**, **state** (a record of what exists; store it remotely with locking, e.g. an S3 bucket + DynamoDB lock, and **protect it: it can contain secrets**). Workflow: `terraform init → plan (review the diff) → apply`. **Drift** (manual changes) is detected by `plan`.
* **Pulumi/CDK**: general-purpose languages for infrastructure.
* **Ansible**: configuration management over SSH (install packages, templates, services).
* **cloud-init / user-data**: bootstrap a VM on first boot.
* **GitOps**: the git repo is the source of truth; a controller (Argo CD, Flux) reconciles the cluster to it; deployments are PRs; audit is git history.
* Policy as code (OPA/Conftest, Checkov, tfsec) in CI to block insecure infrastructure.

A minimal Terraform sketch for this app's single VM (illustrative, provider specifics omitted): a VM resource, a firewall allowing 22/80/443, a DNS A record, a block storage volume for backups, outputs with the IP. Keep **secrets out of Terraform variables files** (use a secret manager or environment variables).

## 28.7 Site Reliability Engineering practices

### SLOs and error budgets (recap and use)

Define SLIs from user experience (turn success rate, p95 turn time, outfit delivery rate, link `live` rate); set SLOs ("99% of turns succeed over 30 days"); the **error budget** is the allowed unreliability. **If the budget is healthy, ship faster; if exhausted, prioritise reliability work** (Chapter 13).

### Toil and automation

**Toil** is manual, repetitive, automatable work that scales with the service. Track it; automate the worst (backups, certificate checks, rotations, deploys).

### On-call and incident management

* **Severity levels** (SEV1 outage ... SEV3 minor) with response expectations.
* **Roles**: incident commander (coordinates), operations (hands on keyboard), communications (updates stakeholders), scribe (timeline).
* **Process**: **detect** (alert) → **triage** (impact, scope) → **mitigate first** (rollback, disable a feature flag, raise a limit, fail over: restore service before finding root cause) → **communicate** (status page, customer updates at fixed intervals) → **resolve** → **learn**.
* **Runbooks**: for each alert, "what it means, how to check, how to fix, who to call". Link them in alert annotations (Chapter 13).
* **Avoid heroics**; sustainable rotations; handoffs; escalate early.

### Blameless postmortems

A written review within days: **summary, impact, timeline, root cause(s) (the contributing factors, using "5 whys" but looking at systems, not people), what went well/badly, where we got lucky, action items with owners and dates**. Blameless means we ask *how the system allowed this*, not *who to blame*, which is the only way people report problems honestly.

Template:

```
Title / date / authors / status
Impact: who was affected, for how long, how badly (numbers)
Timeline (UTC): detection, key decisions, mitigation, resolution
Root cause and contributing factors
Detection: how we found out; could we have found out sooner?
Response: what helped, what hurt
Action items: [prevent] [detect] [mitigate], each with owner and due date
Lessons / what we got lucky about
```

*Example from this project's domain* (hypothetical): "From 14:03 to 15:40 UTC, 100% of new conversations returned 'You have used today's search allowance'. Cause: the **global daily credit cap (25)** was exhausted by a scripted client that created many accounts; per-user caps did not stop it. Detection: a user report (no alert existed on `mcp_limit_hits_total`). Actions: alert on credit usage at 80%, CAPTCHA/email verification on signup, per-IP daily conversation cap, a clearer user-facing message, a 'degraded mode' that serves cached results."

### Capacity planning and load testing

Estimate load (peak concurrent conversations), model it with Little's Law (Chapter 5), **test it**:

* **Never load-test against paid APIs.** Use **demo mode** (`BACKEND_MODE=demo`: scripted model, mock search) so you test *your* system's concurrency, database, streaming and limits at zero cost.
* Tools: **k6**, **Locust**, **Gatling**, **vegeta**, `hey`/`wrk` for simple endpoints.
* Measure: throughput, error rate, latency percentiles, saturation (CPU, memory, DB connections, thread pool), **where it breaks first**.
* Include **soak tests** (hours: leaks), **spike tests**, **stream tests** (hold many SSE connections open).

A Locust sketch against the demo-mode API (the per-user limit of 10 messages/minute means each simulated user must be paced and use its own account):

```python
# locustfile.py: run with: locust -f locustfile.py --host http://localhost:8000
import json, uuid
from locust import HttpUser, task, between

class Shopper(HttpUser):
    wait_time = between(8, 15)                    # respect the 10 messages/minute per-user limit

    def on_start(self):
        email = f"load-{uuid.uuid4().hex[:10]}@example.com"
        r = self.client.post("/auth/register", json={"email": email, "password": "a long load-test passphrase"})
        self.headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    @task
    def conversation(self):
        cid = self.client.post("/conversations", headers=self.headers).json()["id"]
        with self.client.post(f"/conversations/{cid}/messages", headers=self.headers,
                              json={"text": "College wear, around 4000 rupees"}, stream=True,
                              catch_response=True, name="/conversations/{id}/messages") as resp:
            body = resp.text                      # reads the whole SSE stream
            resp.success() if "event: interrupt" in body else resp.failure("no style cards")
```

Expect to hit the **thread-pool ceiling** first (each turn holds a worker thread) and the **registration IP limiter** (30 auth calls/min per IP); both are *features* to understand, not bugs to bypass; for a realistic test use multiple source IPs or raise limits in a test environment *deliberately and documented* (Chapter 12's warning about weakening protections for tests).

### Chaos engineering and game days

Deliberately inject failures to verify resilience: kill a container, block the tool server, make SerpAPI return 500/429/timeouts, fill the disk, break DNS, revoke the model key, skew a clock. Start in staging, with a hypothesis ("the API returns an honest message and the conversation is not stuck"), a blast-radius limit and an abort button. The repo's design already handles several (search outages become friendly messages; the active-turn lock is released on disconnect; stale conversations resume from checkpoints); *test them rather than assume*.

### Disaster recovery

Document **RPO/RTO**, **backups and restores** (drills), **runbooks to rebuild** from git + backups + secrets, **dependency inventory** (model provider, search, DNS, registrar), **communication plan**, and **who has access to what** (bus factor!). Run a **restore drill**, and time it.

## Common mistakes

* A pipeline only the author understands; manual deploys "just this once".
* Tests that skip silently; flaky tests ignored.
* Rebuilding per environment (the thing tested is not the thing deployed).
* Long-lived cloud keys in CI; unpinned third-party actions; secrets exposed to fork PRs.
* Migrations that break the running version; no rollback plan.
* No post-deploy verification or monitoring.
* Load testing paid or third-party APIs.
* Postmortems that blame people and have no owners or dates.
* Alerting on causes instead of user-visible symptoms.

## Summary

* CI/CD turns changes into verified, deployable artifacts quickly and repeatably; build once, promote the same image, deploy by SHA.
* A good pipeline here: lint, type check, unit and integration tests with real Postgres, an offline eval gate, image builds with scans, protected and approval-gated deploys.
* Choose deployment strategy by risk and capacity; migrations must be backward compatible; practise rollbacks.
* AI delivery adds prompts, models, schemas, indexes and eval datasets as versioned artefacts with eval gates and canaries.
* SRE: SLOs and error budgets, runbooks, incident roles, blameless postmortems, load tests in demo mode, chaos exercises, DR drills.

## Key terms

*CI, CD, pipeline, artifact, DORA metrics, test pyramid, blue/green, canary, rolling, feature flag, expand/contract, rollback, IaC, Terraform state, drift, GitOps, SLO, error budget, toil, incident commander, postmortem, load test, soak test, chaos engineering, RPO/RTO.*

## Interview questions

1. What is the difference between continuous delivery and continuous deployment?
2. Design a CI pipeline for this monorepo. What runs on every PR vs nightly?
3. Why "build once, deploy many"? What goes wrong if you rebuild per environment?
4. How do you do a zero-downtime deploy with a database migration?
5. How would you roll out a new prompt or model safely?
6. What belongs in a blameless postmortem? Give an example action item.
7. How would you load-test this app without burning model or search credits?
8. How do you protect CI secrets from malicious pull requests?

## Exercises

1. Add the workflow to `.github/workflows/ci.yml` (on a branch), fix whatever breaks, and make a deliberately failing eval gate turn the build red.
2. Add a scheduled workflow that runs 3 live eval cases nightly with a spend cap and posts the result to a summary/artifact.
3. Implement blue/green on a VM with two compose project names and a Caddy upstream switch; script the cutover and rollback.
4. Write a Terraform configuration (or `gcloud`/`aws` CLI script) for the VM, firewall and DNS record; destroy and recreate it.
5. Run the Locust test against demo mode; find the first bottleneck and write up the capacity estimate.
6. Write a postmortem for a drill where you stop the tool server mid-conversation.
