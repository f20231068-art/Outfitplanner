# Appendix E. Resources

A curated list to deepen each part. Availability, editions and URLs change: search for the title if a link has moved. Prefer **primary documentation** for tools (it matches the version you run) and **books** for lasting concepts.

---

## E.1 General engineering and career

* **The Pragmatic Programmer** (Hunt & Thomas): craft and habits.
* **A Philosophy of Software Design** (Ousterhout): managing complexity.
* **Staff Engineer / The Staff Engineer's Path**: career growth (useful early for context).
* **The Missing Semester of Your CS Education** (MIT, free): shell, Git, debugging, tooling.
* **The Twelve-Factor App** (12factor.net): configuration, processes, logs.
* **Google's *Software Engineering at Google*** and ***Site Reliability Engineering*** (free online).

## E.2 Data structures, algorithms, interviews

* **Introduction to Algorithms** (CLRS) and **The Algorithm Design Manual** (Skiena): reference depth.
* **Grokking Algorithms** (Bhargava): gentle first pass.
* **Cracking the Coding Interview** (McDowell): problems and process.
* **NeetCode** roadmap/150 and **LeetCode** (practice by pattern; use timers).
* **Competitive Programmer's Handbook** (Laaksonen, free).
* Python: **`collections`, `heapq`, `bisect`, `itertools`, `functools`** documentation.

## E.3 Math, probability, statistics

* **Mathematics for Machine Learning** (Deisenroth et al., free).
* **Think Stats** / **Think Bayes** (Downey, free): practical statistics in Python.
* **3Blue1Brown** videos: linear algebra, neural networks, transformers.
* **Statistics Done Wrong** (Reinhart): common mistakes.

## E.4 LLMs and AI engineering

* **AI Engineering** (Chip Huyen): building applications on foundation models.
* **Designing Machine Learning Systems** (Chip Huyen).
* **Anthropic: "Building effective agents"** and the vendor docs for prompting, tool use, structured outputs, prompt caching (read your provider's current documentation).
* **OpenAI, Google, Anthropic, Mistral** API docs; **OpenRouter** docs for gateway behaviour.
* **Andrej Karpathy: "Neural Networks: Zero to Hero"** and "Intro to LLMs".
* **"Attention Is All You Need"** (the transformer paper) and **The Illustrated Transformer** (Alammar).
* **Hugging Face** course and docs (open models, tokenizers).
* **Model Context Protocol**: specification and docs at modelcontextprotocol.io; **FastMCP** docs.
* **LangGraph** docs (concepts: state, persistence, human-in-the-loop); **LangChain** docs.
* **Mastra** docs (agents, workflows, evals, observability).
* **Hamel Husain** and **Eugene Yan** writing on evals and LLM applications; **Simon Willison's blog** (prompt injection, "lethal trifecta", practical LLM tooling).
* **promptfoo**, **Langfuse**, **LangSmith**, **Braintrust**, **Arize Phoenix**, **RAGAS** docs for eval and tracing tools.
* **OWASP Top 10 for LLM Applications**.

## E.5 Retrieval and data

* **Introduction to Information Retrieval** (Manning et al., free): BM25, indexing.
* **pgvector** README; **Pinecone**, **Qdrant**, **Weaviate** learning centres.
* **MTEB** leaderboard (embedding models; test on your own data).

## E.6 Web, networking, backend, front end

* **High Performance Browser Networking** (Grigorik, free): TCP, TLS, HTTP/2, WebSockets.
* **MDN Web Docs**: HTTP, CORS, cookies, fetch, streams.
* **FastAPI**, **Starlette**, **Pydantic**, **uvicorn** docs.
* **React** docs (react.dev: especially "You Might Not Need an Effect"), **Next.js** docs (read the version you run), **TypeScript Handbook**.
* **Web Security Academy** (PortSwigger, free labs): XSS, CSRF, SSRF, access control.

## E.7 Databases

* **Designing Data-Intensive Applications** (Kleppmann): the single best systems book.
* **PostgreSQL documentation** (indexes, transactions, MVCC, `EXPLAIN`).
* **Use The Index, Luke** (free): indexing.
* **SQLBolt**, **Mode SQL tutorial**, **pgexercises.com**: practice.
* **Redis** documentation (data structures, persistence, patterns).

## E.8 Security

* **OWASP Top 10**, **OWASP ASVS**, **OWASP Cheat Sheet Series** (authentication, session, password storage, SSRF, CSRF).
* **Serious Cryptography** (Aumasson) and **Cryptography Engineering**; **Cryptopals** challenges.
* **RFCs**: 7519 (JWT), 8446 (TLS 1.3), 6238 (TOTP), 9106 (Argon2), 6962 (Certificate Transparency), 6749 (OAuth 2.0), 7636 (PKCE).
* **NIST SP 800-63B** (digital identity/passwords).
* **Threat Modeling: Designing for Security** (Shostack).
* **India DPDP Act 2023** text and official rules (consult counsel for obligations).

## E.9 DevOps, containers, cloud, SRE

* **Docker documentation** (Dockerfile best practices, BuildKit, Compose), **Docker Deep Dive** (Poulton).
* **Kubernetes documentation** and **Kubernetes Up & Running**; **Kubernetes the Hard Way** (to understand internals).
* **Caddy** docs (Caddyfile, automatic HTTPS), **nginx** docs.
* **Terraform** docs and tutorials; **Argo CD/Flux** for GitOps.
* **GitHub Actions** docs and "Security hardening for GitHub Actions".
* **Release It!** (Nygard): stability patterns (timeouts, breakers, bulkheads).
* **The Site Reliability Workbook**; **Accelerate** (Forsgren et al.): DORA metrics.
* **Prometheus**, **Grafana**, **OpenTelemetry**, **Jaeger** docs.
* **Linux**: *The Linux Command Line* (Shotts, free), `man` pages, **Julia Evans'** zines.
* **AWS / GCP / Azure** free-tier tutorials; **Oracle Cloud Always Free** (see the deploy guide).

## E.10 System design

* **System Design Interview** vols. 1-2 (Alex Xu) and **Grokking the System Design Interview**.
* **Designing Data-Intensive Applications** (again).
* **High Scalability** blog and company engineering blogs (Netflix, Uber, Stripe, Cloudflare, Discord).
* **ByteByteGo**, **System Design Primer** (GitHub).
* **Papers**: Dynamo, Bigtable, MapReduce, Raft, Spanner (skim abstracts and diagrams).

## E.11 FDE-specific

* Company engineering and careers pages for FDE / applied AI / solutions engineering roles (read actual job descriptions and interview guides).
* **The Mom Test** (Fitzpatrick): customer discovery questions.
* **Crossing the Chasm** / **Inspired** (Cagan): product thinking.
* **Writing**: *On Writing Well* (Zinsser); learn the ADR and postmortem formats (Google SRE postmortem examples).

## E.12 Tools to install and practise with

Python 3.12 + **uv**, Node 22, Docker Desktop, Git, **jq**, **curl**, **psql**, VS Code (+ Python, Docker, REST client), **k6/Locust**, **Postman/HTTPie**, **Wireshark** (for curiosity), **mitmproxy** (inspect your own HTTPS traffic), **Trivy**, **gitleaks**, **pre-commit**.

## E.13 A reading order if time is short

1. *Designing Data-Intensive Applications* (chapters 1-8) alongside Chapters 17 and 30.
2. *AI Engineering* (chapters on prompting, RAG, evaluation, deployment) alongside Chapters 6-14.
3. OWASP Top 10 + LLM Top 10 + one PortSwigger lab per class, alongside Chapters 20-22.
4. Docker/Compose docs + *Release It!* alongside Chapters 25-28.
5. Practice, practice: Chapter 36.
