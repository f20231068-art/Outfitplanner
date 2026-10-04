# The AI Application Engineering Textbook

*Learning to build, secure, deploy and explain production AI applications, using one real project (AI Stylist) as the running example.*

---

## What this book is

You built an AI app by learning on the go: a chat product that asks for an occasion and a budget, plans menswear outfits with a language model, finds real products through a private tool server, verifies every product with rules, and ships behind a hardened Docker deployment with auth, audit logs, evals, tracing and metrics.

That is a lot of technology, and most of it was learned one decision at a time. This book is the version you read *in order*, from first principles, so that you could rebuild the whole thing from a blank folder, **and** so that you can build a different AI product with the same ideas.

It is organised like a university textbook:

* each chapter starts with **learning objectives** and **prerequisites**;
* concepts are explained **from the basics**, with plain-language analogies, then deepened;
* every chapter has an **"In this project"** section that points at the actual code in this repo;
* each chapter ends with **common mistakes, exercises, a summary, key terms, and interview questions**.

It is deliberately long. Nobody should read it in a weekend. Treat it as a course.

## Who it is for

You, as a computer-science student aiming at a **Forward Deployed Engineer (FDE)** role, or any AI-application engineering role. An FDE is the engineer who goes to the customer, understands a messy real-world problem, and ships a working AI-powered solution into the customer's environment. That role needs unusual breadth: coding interviews (DSA), AI engineering, backend and data, security, DevOps, system design, and communication. This book covers all of those, and ties them together.

## How the book is organised

| Part | Chapters | What you get |
|---|---|---|
| **I. Orientation** | 1 | The whole project in one tour: architecture, one request traced end to end, design principles |
| **II. Foundations: programming and DSA** | 2-5 | Mental models, data structures, algorithms, and the math AI engineers actually use. Every structure is tied to code in this repo |
| **III. AI engineering** | 6-15 | LLMs, prompting, structured output, tool use and MCP, agents and LangGraph, RAG, reliability and verification, evals, observability, cost/latency, the vendor landscape |
| **IV. The stack AI sits on** | 16-19 | Networking and the web, databases (Postgres), backend engineering (FastAPI), frontend (React/Next.js) |
| **V. Security** | 20-22 | Cryptography and authentication (JWT, Argon2, refresh rotation), web and AI-specific attacks and defences, audit and tamper evidence |
| **VI. DevOps** | 23-29 | Linux, Git, Docker, Compose and orchestration, reverse proxies/TLS/DNS/cloud, CI/CD and reliability engineering, testing |
| **VII. System design** | 30-32 | Fundamentals, designing AI systems, and how this app would scale step by step |
| **VIII. Career and application** | 33-36 | The FDE role and interviews, a blueprint for any AI app, a question bank, labs and a study plan |
| **Appendices** | A-E | Glossary, cheat sheets, code map, honest limitations and roadmap, resources |

### The chapter list

**Part I: Orientation**
* [01. The project tour](01-project-tour.md)

**Part II: Foundations: programming and DSA**
* [02. Programming mental models](02-programming-foundations.md)
* [03. Data structures](03-data-structures.md)
* [04. Algorithms and problem solving](04-algorithms.md)
* [05. Math, probability and statistics for AI engineers](05-math-for-ai.md)

**Part III: AI engineering**
* [06. How language models work](06-llm-fundamentals.md)
* [07. Prompting and structured output](07-prompting-and-structured-output.md)
* [08. Tool use and the Model Context Protocol](08-tools-and-mcp.md)
* [09. Agents and LangGraph](09-agents-and-langgraph.md)
* [10. Retrieval, embeddings and memory (RAG)](10-rag-and-retrieval.md)
* [11. Reliability and verification: "the model proposes, code disposes"](11-reliability-and-verification.md)
* [12. Evaluating AI systems](12-evaluation.md)
* [13. Observability: logs, metrics, traces](13-observability.md)
* [14. Cost, latency and model choice](14-cost-latency-models.md)
* [15. Vendors, frameworks and alternatives](15-vendors-and-frameworks.md)

**Part IV: The stack AI sits on**
* [16. Networking and the web](16-networking-and-web.md)
* [17. Databases](17-databases.md)
* [18. Backend engineering with FastAPI](18-backend-fastapi.md)
* [19. Frontend for AI apps](19-frontend.md)

**Part V: Security**
* [20. Cryptography and authentication](20-crypto-and-authn.md)
* [21. Web and AI application security](21-web-and-ai-security.md)
* [22. Integrity, audit and tamper evidence](22-integrity-and-audit.md)

**Part VI: DevOps**
* [23. Linux and the shell](23-linux-and-shell.md)
* [24. Git and collaboration](24-git.md)
* [25. Docker](25-docker.md)
* [26. Docker Compose and orchestration](26-compose-and-orchestration.md)
* [27. Reverse proxies, TLS, DNS and the cloud](27-proxies-tls-cloud.md)
* [28. CI/CD and site reliability](28-cicd-and-sre.md)
* [29. Testing](29-testing.md)

**Part VII: System design**
* [30. System design fundamentals](30-system-design-fundamentals.md)
* [31. Designing AI systems (with worked cases)](31-ai-system-design.md)
* [32. Scaling this app, step by step](32-scaling-this-app.md)

**Part VIII: Career and application**
* [33. The Forward Deployed Engineer role and interviews](33-fde-role-and-interviews.md)
* [34. The blueprint: building any AI product](34-blueprint-any-ai-app.md)
* [35. Question bank](35-question-bank.md)
* [36. Labs and a study plan](36-labs-and-study-plan.md)

**Appendices**
* [A. Glossary](A-glossary.md)
* [B. Cheat sheets](B-cheatsheets.md)
* [C. Code map: file to concept](C-code-map.md)
* [D. Honest limitations and roadmap](D-limitations-and-roadmap.md)
* [E. Resources](E-resources.md)

## Three reading paths

**Path 1: "I want to rebuild this project from scratch."**
Read 1, then 2-4 quickly, then 16-18, 6-9, 11, 20-22, 25-27, then 29. Do the labs in chapter 36 as you go.

**Path 2: "I need to pass interviews in 8-12 weeks."**
Chapters 2-4 and 30-31 daily (with the question bank in chapter 35), then one chapter per day from the other parts in the order of the study plan in chapter 36.

**Path 3: "I want to build a different AI product."**
Read 1, then 34 (the blueprint), and dip into chapters as the blueprint's checklists point to them.

## Conventions used in this book

* **File paths** are relative to the repo root, for example `services/api/src/api/agent/graph.py`. Function names are given so the text still points at the right place after the code changes. (Line numbers drift, names do not.)
* **"In this project"** boxes describe the real code. **"Beyond this project"** boxes describe what you will meet elsewhere but this repo does not use.
* **Honesty markers.** Where this app does something simplistic (an in-memory rate limiter, no backups), the book says so, explains the limit, and says what the production fix is. Knowing the limits of your own system is a core engineering skill, and it is exactly what interviewers probe.
* **Python** is the main language (3.12). **TypeScript** appears in the web app and the evals app. Examples are short and runnable unless marked as pseudocode.
* **Versions.** The AI tooling world changes monthly. The code in this repo pins what worked at build time (LangGraph 1.x, FastMCP 4.x, Next.js 16, Mastra 1.x). When a chapter describes a library, treat the *concepts* as stable and the *API details* as "check the current documentation". The book points out where this repo hit a version trap.
* **Prices and quotas** are never quoted as facts because they change. The book shows how to *calculate* with them.

## A study method that works

1. **Read** a section. Close the book.
2. **Explain it** out loud in two minutes as if to a friend. Where you stumble, reread.
3. **Find it in the code.** Open the file the chapter names and read it with the new vocabulary.
4. **Break it.** The labs in chapter 36 ask you to change one line and predict what fails. Predicting wrongly is where learning happens.
5. **Teach it.** Write the three-sentence version in your own words. If you cannot, you do not own it yet.

For DSA specifically: do not read solutions first. Spend 25 minutes stuck on a problem before looking. Being stuck is the workout.

## A note on what an "exhaustive understanding" means

No book makes you an expert in Docker, Postgres, cryptography and LLMs simultaneously. What it can do is give you a **correct mental model** of each, so that when you meet an unfamiliar tool you can place it ("this is another reverse proxy", "this is another vector store", "this is a vendor's version of tool calling"), reason about its trade-offs, and learn the details quickly. That is the skill that transfers to "any AI app or product", and it is the skill an FDE is paid for.

Let's start with the whole picture.
