# Chapter 33. The Forward Deployed Engineer Role and Interviews

> **Learning objectives.** Understand what a Forward Deployed Engineer (FDE) does and how the role differs from neighbouring roles; run a customer engagement from discovery to handoff; handle customer-environment realities; prepare for each stage of an FDE interview loop (coding, practical build, system design, decomposition case, behavioural); turn this project into compelling, honest stories; and communicate like someone customers trust.
>
> **Prerequisites.** The rest of the book helps; this chapter is the bridge from knowledge to a job.

---

## 33.1 What an FDE is

The title came from **Palantir**, which embedded engineers with customers to make complex data platforms work in real organisations. It has spread to AI companies, data platforms and startups: an FDE is an **engineer who works directly with customers** to understand a real, messy problem and **ship a working solution into the customer's environment**, then feed what they learn back into the product.

### One-sentence version

> *Part software engineer, part consultant, part product manager for one customer's success.*

### What they do day to day

* Meet customers to understand goals, workflows and constraints; translate business problems into technical ones.
* **Prototype quickly** (days, not quarters): an agent, a pipeline, an integration, a dashboard.
* Integrate with **customer systems and data** (APIs, databases, spreadsheets, SSO, file shares).
* **Evaluate** whether the AI actually works on the customer's data; set honest expectations.
* **Deploy and operate** in the customer's cloud/on-prem environment under their security rules.
* **Train users**, gather feedback, iterate, and measure outcomes.
* **Write up** what was built (docs, runbooks, decision records) and **escalate product gaps** to internal engineering.
* Sometimes: scope and **demo** pre-sales, **debug production** at a customer at an awkward hour, **travel** to customer sites.

### How it differs from nearby roles

| Role | Primary focus | Difference from FDE |
|---|---|---|
| **Software engineer (product)** | builds the *general* product for many customers; deep ownership of a codebase | FDE builds *for one customer* first and owns the outcome there; more breadth, less depth in one codebase |
| **Solutions architect / sales engineer** | designs and demos, supports the sale, often does not build production systems | FDE **builds and deploys**, stays through delivery |
| **Consultant** | advises, produces recommendations and slides | FDE **writes the code** and runs it |
| **Support / customer-success engineer** | resolves tickets, onboarding | FDE does proactive, custom engineering |
| **Data scientist / ML engineer** | models and experiments | FDE integrates models into working systems and customer workflows; heavy on engineering and communication |
| **DevOps / SRE** | platform reliability | FDE touches deployment and reliability but for a specific customer solution |

The role rewards **breadth** (this book's table of contents), **speed with judgement**, **ownership**, and **communication**.

### Why it is well paid, even early

Companies lose or win large contracts on whether the product works inside the customer's reality. An engineer who can handle ambiguity, write code, understand security and deployment, and talk to executives is scarce. The cost is **breadth to maintain**, **context switching**, **customer pressure**, and often **travel**.

## 33.2 The skills map (and where this book covers each)

| Area | Examples | Chapters |
|---|---|---|
| **Core coding** | Python/TypeScript, DSA, clean code, testing | 2-4, 29 |
| **Data and SQL** | joins, modelling, CSV/JSON wrangling | 5, 17 |
| **AI engineering** | prompting, structured output, tools/MCP, agents, RAG, evals, cost/latency | 6-15 |
| **Web/backend/frontend** | HTTP, APIs, auth, streaming, React | 16-19 |
| **Security and privacy** | auth, secrets, injection, SSRF, prompt injection, compliance | 20-22 |
| **DevOps/cloud** | Linux, Git, Docker, CI/CD, deployment, observability | 23-28 |
| **System design** | scaling, reliability, trade-offs | 30-32 |
| **Customer skills** | discovery, scoping, expectation setting, demos, writing, negotiation of scope | this chapter |
| **Product sense** | what is valuable, what is the smallest slice, how to measure | this chapter, 34 |

## 33.3 The engagement lifecycle

### 1. Discovery (days 1-5)

Goal: understand the **problem, the people, the data, and the definition of success** before building.

Questions to ask:

* **Goal**: What outcome do you want? What would success look like in numbers (time saved, tickets deflected, error rate, revenue)? What happens today?
* **Users and stakeholders**: who uses it, who pays, who can block it (security, legal, IT, procurement)?
* **Workflow**: walk me through a real example, step by step, with screens and documents. What is the exception path?
* **Data**: where does it live, who owns it, how clean is it, how often does it change, is it sensitive, do we have permission and access, are there samples?
* **Systems**: what must we integrate with (CRM, ERP, SSO, ticketing)? APIs available? Rate limits? Test environments?
* **Constraints**: security/compliance requirements, data residency, approved vendors and models, network restrictions, deployment environment (cloud/on-prem/air-gapped), timeline, budget.
* **Risk tolerance**: what is the cost of a wrong answer? Who reviews?
* **Existing attempts**: what has been tried, what failed, why?
* **Evaluation**: do you have labelled examples, expert reviewers, ground truth?

Deliverable: a **one-page problem statement** (goal, users, scope, non-goals, success metrics, risks, assumptions) the customer agrees to in writing.

### 2. Scoping and a proof of concept (weeks 1-3)

* Pick the **smallest slice that proves value** with **real customer data**.
* Define the **evaluation up front** (a labelled set, rubric, acceptance threshold) so "it works" is measurable (Chapter 12).
* Build a thin **end-to-end** path first (walking skeleton) with fakes at the edges, then replace fakes with real integrations (the order this project followed, Chapter 1).
* **Demo early and often**; show real outputs, including failures, and what you will do about them.
* **State risks and unknowns explicitly**; give ranges, not false precision.

### 3. Build for production (weeks 3-8)

* Add the unglamorous parts: **auth/SSO, permissions, validation, error handling, rate limits, logging, monitoring, backups, tests, CI/CD, documentation** (Parts IV-VI).
* **Security and compliance review** with the customer's team: data flow diagram, threat model, DPA with model providers, secrets handling, access controls (Chapters 20-22).
* **Deploy into the customer's environment**; expect friction (firewalls, proxies, approvals).
* **Evaluate on real data**, iterate on prompts/retrieval/verification, publish the scorecard.

### 4. Launch and adoption

* **Pilot** with a small group; collect feedback; fix top issues; train users; write a quick-start.
* **Monitor** quality, cost, latency, errors; set alerts; define support and escalation paths.
* **Manage expectations**: what the system does well, where humans must review, how errors are reported.

### 5. Handoff or productise

* **Runbooks, architecture docs, decision records, on-call guidance**; train the customer's engineers.
* **Feed back to product**: reusable components, missing features, common requests. The best FDE work becomes product.

### Playbook: your first week at a customer

1. Get access (accounts, VPN, repos, data samples, test environments) *immediately*; access takes the longest.
2. Meet the sponsor, the day-to-day users, and the gatekeepers (security/IT).
3. Shadow a real workflow.
4. Write the problem statement; get sign-off.
5. Build a throwaway prototype of the riskiest assumption (can we reach the data? can the model do the core task on 10 real examples?).
6. Set up a **weekly demo** and a **written status update** (progress, risks, asks, next steps).
7. Keep a **decision log** and a **risk register**.

### Managing expectations and saying no

* Customers often hear "AI can do anything". Calibrate with **evidence from their data**: "On 50 of your invoices it extracted totals correctly 94% of the time; the failures are scanned faxes."
* **Name the trade-offs**: accuracy vs cost vs latency vs effort.
* **Say no with alternatives**: "I would not automate refunds above ₹X yet; here is a human-approval design that gets 80% of the benefit."
* **Under-promise, over-deliver**; surface bad news early and with a plan.
* **Separate demo from production**: a polished demo can hide missing security, scale and evaluation; be explicit about the gap.

## 33.4 Customer environment realities (the part nobody teaches)

| Reality | What it looks like | What to do |
|---|---|---|
| **Locked-down network** | no outbound internet; allow-listed domains only; TLS-inspecting proxy | ask for egress rules early; trust the corporate CA (never disable verification); consider on-prem/open models or private endpoints (Bedrock/Vertex/Azure) |
| **SSO and identity** | Okta/Entra ID/SAML/OIDC required; no local passwords | integrate OIDC; map roles/groups to permissions; do not build login (Chapter 20) |
| **Data silos and quality** | exports in odd formats, Excel as the database, undocumented fields | profile data first; build tolerant parsers (as `PrefsExtraction` tolerates "4k"); document assumptions; validate |
| **Security review gates** | questionnaires, pen-test demands, data-flow diagrams | prepare early with the Chapter 21 checklist and the residual-risk register |
| **Compliance** | SOC 2, HIPAA, PCI, GDPR, India DPDP Act | know what data classes you touch; minimise; DPAs; retention; audit logs (Chapter 22) |
| **Slow approvals and procurement** | weeks for a firewall rule or a vendor sign-off | start the paperwork on day one |
| **Heterogeneous infra** | different cloud, Windows servers, legacy systems, mainframes | containers and twelve-factor configuration make you portable; keep adapters at the edges |
| **Air-gapped / on-prem** | no cloud model APIs | open-weight models, self-hosted vector stores; plan GPU capacity |
| **Change management** | users resist new tools | involve users early; training; champions; measure adoption |
| **Politics** | stakeholders with conflicting goals | clarify decision rights; get written scope; escalate calmly |
| **Support burden after launch** | "it's broken" with no details | logging with trace ids, feedback buttons, runbooks, a support rota |

## 33.5 The FDE interview loop

Loops vary by company, but a typical sequence for early-career FDE candidates:

1. **Recruiter screen**: motivation, background, logistics (travel, location), a few basic technical questions.
2. **Technical screen / coding round(s)**: one or two data-structures-and-algorithms problems (Chapter 4), sometimes with a **practical** flavour (parse messy data, call an API, handle errors).
3. **Practical build** (take-home or live, 1-4 hours): build a small service, agent or data pipeline; judged on structure, tests, error handling, README, and how you explain trade-offs.
4. **System design**: classic (Chapter 30) and increasingly **AI system design** (Chapter 31).
5. **Decomposition / customer case** ("deployment" interview): you are given a vague customer problem; you ask questions, scope, design, and discuss rollout and risks (Section 33.7).
6. **Behavioural / hiring-manager**: ownership, ambiguity, conflict, failure, learning (Section 33.8), plus a project deep dive (Section 33.9).
7. Sometimes a **values/leadership** round or a **presentation** of a past project.

**What is being assessed**: raw problem solving, practical engineering, breadth of knowledge, **communication under ambiguity**, customer empathy, ownership and judgement, and learning speed.

### Preparation plan (summary; full plan in Chapter 36)

* 100-150 DSA problems with review (Chapter 4) across the main patterns.
* Re-read Chapters 6-15 and 20-22 until you can answer the question bank without notes (Chapter 35).
* Build or extend one real project end to end (this one) and **be able to explain every decision**.
* Do 6-10 mock system designs and 4-6 mock decomposition cases out loud.
* Prepare 8 behavioural stories (below).
* Research the company's products, customers and recent launches.

## 33.6 Coding rounds

### Algorithmic (Chapter 4)

Use the method: clarify, example, brute force, optimise with a pattern, code, test, complexity. Talk throughout. Practise in the language you will use (Python is a good default; know its standard library: `collections`, `heapq`, `bisect`, `itertools`).

### Practical coding

Typical prompt: *"Here is a CSV/JSON of customer tickets and an API; write a script that classifies and posts them."* Show professional habits:

* **Read the data first** (print samples, count missing values).
* **Handle bad data and failures**: validation, timeouts, retries with backoff, partial failure; do not crash on the first malformed row.
* **Structure**: small functions, clear names, types (Pydantic or dataclasses), a `main`.
* **Test the core logic** (a couple of pytest cases) even in 45 minutes.
* **Configuration via environment variables**; no secrets in code.
* **Explain trade-offs aloud** and note what you would do with more time (logging, idempotency, pagination, rate limits, concurrency, metrics).
* **Use AI assistants only if allowed**, and disclose; understand every line you submit.

### A skeleton you can adapt in 5 minutes

```python
import csv, json, logging, os, sys, time
import httpx
from pydantic import BaseModel, ValidationError

log = logging.getLogger("job")

class Ticket(BaseModel):
    id: str
    text: str

def load(path: str) -> list[Ticket]:
    good, bad = [], 0
    with open(path, newline="", encoding="utf-8") as f:                 # always specify the encoding
        for row in csv.DictReader(f):
            try: good.append(Ticket(**row))
            except ValidationError: bad += 1                              # count and move on; report at the end
    log.info("loaded %d tickets, skipped %d invalid", len(good), bad)
    return good

def post(client: httpx.Client, t: Ticket, label: str, tries: int = 3) -> bool:
    for i in range(tries):
        try:
            r = client.post("/classify", json={"id": t.id, "label": label}, timeout=10)
            if r.status_code < 500 and r.status_code != 429: return r.is_success
        except httpx.TransportError: pass
        time.sleep(0.5 * 2 ** i)                                          # backoff (add jitter in real code)
    return False
```

## 33.7 The decomposition / customer case interview

You are given something vague: *"A logistics company wants AI to handle its customer-support emails."* The interviewer wants to see **structured thinking, good questions, pragmatism, and risk awareness**, not a perfect architecture.

### A framework

1. **Clarify the goal and metrics.** What is the business outcome? (First-response time? Cost per ticket? CSAT?) How is it measured today? What volume? What languages? What is the cost of a wrong reply?
2. **Map the current workflow.** Who reads emails, how are they categorised, what systems are consulted (order tracking, billing), what actions are taken (refund, reship), what escalations exist?
3. **Segment the work.** Break the volume into categories (80% are "where is my order?" and "change address", 15% claims, 5% complaints). **Pick the highest-volume, lowest-risk slice first.**
4. **Assess data and access.** Do we have past tickets and resolutions (for evals and few-shot)? Order-system APIs? PII constraints? Can data leave their cloud?
5. **Design the MVP.** Likely: classify + extract fields + look up order status via a *read-only tool* + draft a reply for a human to approve. Autonomy ladder step 2 (Chapter 31). Use **deterministic validation** where possible; **citations** to the order data.
6. **Define evaluation.** Labelled historical tickets; metrics (classification accuracy, factual correctness vs system of record, draft acceptance rate, escalation precision); human review sample; a shadow-mode period.
7. **Risks and mitigations.** Wrong promises (refunds), PII leakage, hallucinated tracking info, prompt injection via email content, cost, rate limits, model drift, adoption by agents. Mitigate: read-only tools, approval gates, strict templates for commitments, redaction, spend caps, monitoring.
8. **Rollout.** Shadow mode → assist mode for one queue → partial automation for the safest category with sampling review → expand; success criteria for each step; rollback plan.
9. **Operations.** Dashboards, alerts, feedback loop into the eval set, owner and on-call.
10. **What I would *not* do first**: full autonomy, many integrations, fine-tuning.

Practise with: insurance claims intake, clinic appointment scheduling, e-commerce returns, HR policy Q&A, procurement invoice matching, sales-call summaries, IT helpdesk triage, KYC document checks.

## 33.8 Behavioural interviews

### STAR

**Situation** (brief context), **Task** (your responsibility), **Action** (what *you* did, specifically, with reasoning), **Result** (measurable outcome and what you learned). Keep each story to ~2 minutes. Use "I", not "we", for your contribution; quantify; include **trade-offs, mistakes and what you changed afterwards**.

### Themes to cover (prepare a story for each)

1. **Ownership**: you took responsibility beyond your role.
2. **Ambiguity**: a vague problem you scoped and solved.
3. **Technical depth**: the hardest bug or design you handled.
4. **Customer/user empathy**: you changed something because of a user need.
5. **Conflict or disagreement**: how you resolved it respectfully.
6. **Failure**: what went wrong, your part, what you changed.
7. **Learning fast**: a technology you mastered under pressure.
8. **Influence without authority / communication**: you convinced someone with evidence.
9. **Prioritisation and trade-offs**: what you cut and why.

### Eight stories drawn from this project (templates with the true facts)

Use these as *structures*; fill in your own feelings, numbers and details, and only claim what you did.

1. **Testing the vendor's claim (technical depth, learning).** *Situation:* the chosen free chat model was expected to support structured JSON output. *Action:* I tested instead of assuming: `json_schema` was rejected, plain JSON mode returned nulls, tool-calling worked; I made the output method a configuration setting and documented why. *Result:* reliable structured output on a free model, and a retry-and-validate layer that survives bad outputs. *Lesson:* vendor capabilities are things you measure.
2. **Dropping a layer (prioritisation).** *Situation:* the plan included a TypeScript Mastra gateway between the UI and the API. *Action:* I questioned what problem it solved, found none, removed it, and repurposed Mastra for evals, tracing and audit. *Result:* fewer hops, simpler security, and a useful eval harness. *Lesson:* every layer must earn its place.
3. **Designing around the data (customer/user empathy and data-driven design).** *Situation:* product search results rarely state colour. *Action:* I measured it (~11% of titles), designed a three-valued verifier with an *assumed colour* fallback flagged as low confidence, and showed the uncertainty to users. *Result:* ~54% of results became usable without lying about confidence. *Lesson:* design for the data you have and be honest about uncertainty.
4. **Security by layers (ownership).** *Situation:* a tool server that fetches URLs and spends paid credits. *Action:* private network only, signed single-use tokens, host/origin checks, rate limits and credit caps, SSRF defences with IP pinning, tests for each attack. *Result:* a tool server that cannot be used on its own and whose worst-case spend is bounded. *Lesson:* assume each control can fail.
5. **A secret in the wrong file (failure).** *Situation:* real API keys were pasted into a committed example file and one was printed in a terminal. *Action:* rotated the keys, added a hygiene test that fails on key-shaped strings, and adopted a rule to print only variable names. *Result:* the mistake can no longer recur silently. *Lesson:* own mistakes quickly; turn them into controls.
6. **A latency mystery (debugging).** *Situation:* the first request in a process hung ~40 seconds. *Action:* isolated it to network behaviour (an IPv6 attempt stalling before falling back) and pinned outbound connections to IPv4 with a setting. *Result:* predictable latency. *Lesson:* test on the real network; latency bugs are often not in your code.
7. **Making failures visible (ownership of quality).** *Situation:* "the AI works" had no evidence behind it. *Action:* built a 13-case eval harness driving the real API as a shopper, with 8 hard gates and 4 soft signals, tracing, and an audit chain; stated honestly that demo mode proves plumbing, not model quality. *Result:* regressions in guarantees fail the build; limits are documented. *Lesson:* measure, and be honest about what the measurement covers.
8. **Deployment hardening (breadth).** *Situation:* moving from a laptop to a deployable system. *Action:* hardened containers (non-root, read-only, dropped capabilities), one public door (Caddy), automatic HTTPS, fail-fast configuration, scripts that generate secrets without printing them, and a deployment guide with honest limits (no backups yet). *Result:* a reproducible deployment layout. *Lesson:* production is a set of boring, deliberate defaults.

### Questions you should be ready to answer

* "Tell me about a time you had to learn something quickly."
* "Describe a project where requirements were unclear."
* "A customer insists on a feature you think is a bad idea. What do you do?"
* "Tell me about a bug that took you a long time."
* "How do you decide what to build first?"
* "What would you do if you discovered a security issue the customer did not want to hear about?" (Answer: raise it clearly, with evidence and options, escalate through the agreed channel; never hide it.)
* "Why FDE rather than SWE?"

## 33.9 Presenting this project

### The 30-second version

> *"I built an AI stylist for menswear in India. You give an occasion and a budget; a LangGraph agent proposes styles, plans outfits, searches real stores through a private tool server, and a rule-based verifier checks every product before it's shown. I also built the auth, audit log, evals, observability and a hardened Docker deployment behind Caddy."*

### The 2-minute version

Add: the **problem** (LLMs hallucinate products and budgets), the **principle** ("the model proposes, code disposes"), the **architecture** (Next.js → Caddy → FastAPI/LangGraph → private MCP tool server → SerpAPI, Postgres for state), **two or three decisions** (tool-calling for structured output on a free model; MCP server private with signed single-use tokens; verifier with three-valued logic), **how you know it works** (evals with gates, 224+ tests), and **what you'd do next** (Redis for shared state, backups, paid model, taste judge).

### The 10-minute demo script

1. State the problem and the principle (30 s).
2. Live demo (3 min): register, ask "college wear, around ₹4000", show progress events, pick a style, show outfits with the **confidence badge**, click **Buy**.
3. Architecture diagram (2 min): the five servers and the private network (Chapter 1b).
4. One deep dive of the interviewer's choice (3 min): verifier, tool-server security, graph interrupts, or audit chain.
5. Honest limits and roadmap (1.5 min): in-process state, no backups, free model, no MFA, not publicly launched.

### Be accurate: what you can and cannot claim

* **Claim**: built, tested, containerised and verified end to end locally, with a deployment layout ready for a small server; offline evals and extensive tests.
* **Do not claim**: production users, proven model quality (the evals prove guarantees and plumbing; real-model evals and a taste judge are not built), scalability beyond one node, or compliance certifications.
* **Own the gaps** with a plan; interviewers trust candidates who know their system's limits (Chapters 21, 32, Appendix D).

### Likely deep-dive questions on this project (answers are in the chapters)

1. Why is the tool server a separate service? (1b, 8, 21)
2. How do the signed tokens work and what stops replay? (20)
3. How does the agent pause for user input and resume? (9)
4. How does the verifier decide, and where can it be wrong? (11)
5. How would you scale this to 1,000 concurrent users? (32)
6. What happens when the model returns invalid JSON? (7)
7. How do you prevent prompt injection? (21)
8. How do you know it works? (12)
9. Walk me through a deployment. (27, 1b)
10. What would you change if you rebuilt it? (Appendix D)

## 33.10 Communication skills

* **Know your audience**: executives (outcome, risk, cost), users (how it helps them), engineers (design, trade-offs), security (data flow, controls).
* **Explain without jargon**; use analogies; anchor in their example.
* **Write well**: status updates (progress, risks, asks, next steps); design docs (problem, options, decision, consequences); runbooks; postmortems.
* **Run good meetings**: agenda, outcomes, owners, follow-up in writing.
* **Disagree productively**: bring evidence, propose options, accept the decision once made (or escalate through the agreed path).
* **Document decisions** (ADRs) so the *why* survives people changing.
* **Listen more than you talk** in discovery; repeat back what you heard.
* **Be honest about uncertainty**; "I don't know yet; here is how I'll find out" builds trust.

## 33.11 Evaluating offers and negotiating (briefly)

* Compare **total compensation** (base, bonus, equity with vesting/refresh, benefits), **location and travel expectations** (percentage of time on site), **customer mix** (enterprise vs startup, regulated industries), **on-call and support load**, **team and mentorship**, **growth path** (to senior FDE, tech lead, product, engineering).
* Research ranges from public sources and peers; ask the recruiter for the band; **negotiate politely with data** and in writing; equity is worth what the company is worth, so ask about valuation, dilution and liquidity.
* Ask questions that reveal reality: "Describe a typical engagement; what percentage is coding vs meetings? How much does the team reuse code between customers? How are FDEs evaluated?"

## 33.12 Portfolio and growth

**Portfolio checklist** for this project:

* [ ] A clear **README** (what, why, architecture diagram, how to run, security summary, honest limitations).
* [ ] A 3-minute **demo video** and screenshots.
* [ ] **Architecture and decision records** (why MCP, why verification, why skipped the gateway).
* [ ] **Eval results** and what they mean (and don't).
* [ ] **Tests passing** badge (CI configured: Chapter 28).
* [ ] A short **write-up/blog** on one lesson (e.g. "what I learned making an LLM agent verify its own products").
* [ ] **A deployed demo** (small VM) with demo mode so reviewers can try it free.
* [ ] Clean git history and no secrets (run the hygiene test).

**Growth habits:** build small things weekly; read postmortems and engineering blogs; write notes (a "til" repo); contribute to an open-source tool you use; give a lunch-and-learn; keep a list of customer-problem patterns you have solved.

## 33.13 Green flags and red flags in FDE roles

| Green flags | Red flags |
|---|---|
| a clear product and a feedback path from field to engineering | "FDE" used as a euphemism for unpaid support or pure sales demo duty |
| scoped engagements with success metrics | open-ended custom work with no productisation |
| mentorship and reusable internal tooling | constant travel with no support; no on-call boundaries |
| security and evaluation taken seriously | pressure to ship demos as production; no evals |
| respect for engineering quality | "just make the demo work" culture |

## 33.14 Customer-site toolkit checklist

* Laptop with Docker, Python (uv), Node, Git, a good editor, a password manager, VPN client; a **clean, minimal demo environment you can recreate in minutes**.
* A **synthetic dataset** and a **demo mode** (like `BACKEND_MODE=demo`) so you can show the product when the network or APIs fail.
* **Offline docs** (this textbook, API docs), cheat sheets (Appendix B).
* **Security hygiene**: disk encryption, screen lock, no secrets in shell history, separate customer credentials, least privilege.
* **Communication tools**: screen sharing, a diagramming tool, templates for status updates and postmortems.
* **A notebook** for decisions and open questions.

## Common mistakes

* Building before understanding the problem and success metric.
* Overpromising AI capabilities; demoing only the happy path.
* Ignoring the customer's security/compliance gates until late.
* Hand-waving about evaluation.
* Not writing things down (scope, decisions, risks).
* Treating a prototype as production.
* In interviews: silent coding, no clarifying questions, claiming more than you built.

## Summary

* An FDE embeds with customers, prototypes fast, integrates with their systems, deploys under their constraints, measures outcomes, and feeds learnings back to the product.
* Run engagements as discovery → scoped POC with evals → production hardening → pilot → handoff/productise, with written scope, risks and weekly demos.
* Expect locked-down networks, SSO, compliance and slow approvals; keep your solutions portable and secure.
* Interview loops test coding, practical building, system design (including AI), decomposition of messy customer problems, and behaviour; prepare each deliberately.
* Turn this project into honest, specific stories; know its limits as well as its strengths.

## Key terms

*FDE, discovery, proof of concept, walking skeleton, scope, non-goals, success metric, shadow mode, autonomy ladder, STAR, decomposition case, ADR, runbook, handoff, productise.*

## Interview questions

1. What does an FDE do? How is it different from a software engineer or solutions architect?
2. A customer wants "AI for our emails". How do you start?
3. How do you decide what to build in a two-week proof of concept?
4. A customer's network blocks all outbound traffic. What are your options?
5. Tell me about a time you made a mistake. What changed afterwards?
6. How do you handle a stakeholder asking for something risky?
7. Describe your most technically challenging project.
8. Why do you want to be an FDE?

## Exercises

1. Write the one-page problem statement for three hypothetical customers (insurance claims, clinic scheduling, e-commerce returns).
2. Record yourself giving the 2-minute and 10-minute project pitches; watch them; fix filler and unclear parts.
3. Write all nine behavioural stories with true details and quantified results.
4. Run three mock decomposition cases with a friend using the framework in 33.7.
5. Build a one-day practical project (a CSV → API pipeline with tests and a README) timed at 3 hours.
