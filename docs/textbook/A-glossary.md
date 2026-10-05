# Appendix A. Glossary

Alphabetical. Each entry is a one-to-three-line definition; the chapter number points to the full treatment. Terms specific to this project are marked **(repo)**.

---

**A**

* **ACID** (17): Atomicity, Consistency, Isolation, Durability: guarantees of database transactions.
* **Access token** (20): short-lived credential sent with each API request; here a 15-minute RS256 JWT kept in browser memory.
* **ACME** (27): protocol for automatic certificate issuance (Let's Encrypt); Caddy uses it.
* **Adapter / provider** (8, 15): a module that hides one external service behind your own interface (`providers/serpapi.py`) **(repo)**.
* **Advisory lock** (17): an application-defined lock held in Postgres (`pg_advisory_lock`); used for migrations and the audit chain **(repo)**.
* **Agent** (9): a system where a model decides the next action in a loop based on results; contrast with a workflow.
* **AEAD** (20): authenticated encryption with associated data (AES-GCM, ChaCha20-Poly1305).
* **Amortised cost** (3): average cost per operation over a sequence (list append is O(1) amortised).
* **ANN** (5, 10): approximate nearest-neighbour search (HNSW, IVF).
* **API gateway** (30): front service handling auth, rate limits, routing for many backends.
* **Argon2id** (20): memory-hard password-hashing function; this app's choice **(repo)**.
* **ASGI** (18): asynchronous Python web server interface (uvicorn, FastAPI).
* **Assumed attribute** (11): a value trusted from the search query rather than read from product data, lowering confidence **(repo)**.
* **At-least-once delivery** (30): a message may be delivered more than once; consumers must be idempotent.
* **Attention** (6): transformer mechanism weighting how much each token uses others.
* **Audit log** (22): append-only record of who did what; here hash-chained **(repo)**.
* **Authentication / authorisation** (20): proving identity / deciding permissions.
* **Availability** (30): fraction of time a service works (the "nines").
* **Avalanche effect** (20): tiny input change flips about half of a hash's bits.

**B**

* **Backoff (exponential, with jitter)** (4, 11): increasing, randomised waits between retries.
* **Backpressure** (30): refusing/slowing work when a downstream is saturated.
* **Base model** (6): pre-trained model before instruction tuning.
* **Batch API** (14): asynchronous bulk requests at a discount.
* **bcrypt / scrypt / PBKDF2** (20): password-hashing functions.
* **Bearer token** (16, 20): credential sent as `Authorization: Bearer <token>`.
* **BFS / DFS** (3): breadth-first / depth-first graph traversals.
* **Big-O** (3): upper bound on growth rate of cost with input size.
* **Blue/green deployment** (28): two full environments with a traffic switch.
* **BM25** (10): lexical ranking function used in search.
* **Bloom filter** (3): compact probabilistic set with no false negatives.
* **Bulkhead** (11, 30): isolating resource pools so one failure does not starve others.
* **Build context** (25): the files sent to the Docker builder.
* **BuildKit** (25): Docker's modern builder (cache mounts, secret mounts).

**C**

* **Cache-aside** (30): app checks cache, loads from source on miss, fills cache.
* **Cache stampede** (30): many simultaneous misses overload the source.
* **Canary release** (28): send a small traffic share to the new version first.
* **CAP theorem** (17, 30): under a partition choose consistency or availability.
* **Capability (Linux)** (23, 25): a slice of root's power; containers drop them all **(repo)**.
* **cgroup** (23): kernel feature limiting CPU/memory/PIDs for a process group.
* **Chain-of-thought** (7): prompting the model to reason step by step.
* **Checkpoint / checkpointer** (9): saved graph state per step; `PostgresSaver` **(repo)**.
* **Chunking** (10): splitting documents into retrievable pieces.
* **CI/CD** (28): continuous integration / delivery or deployment.
* **Circuit breaker** (11, 30): stops calls to a failing dependency, then probes recovery.
* **CIDR** (16): network notation like `10.0.0.0/8`.
* **Closure** (2): a function remembering variables of its defining scope.
* **Compose (Docker)** (26): tool defining multi-container apps in YAML.
* **Confidence (high/low)** (11): verifier's certainty label shown to users **(repo)**.
* **Connection pool** (17): reusable set of open DB connections.
* **Consistent hashing** (30): hashing scheme that remaps few keys when nodes change.
* **Constant-time comparison** (20): equality check that does not leak via timing (`hmac.compare_digest`).
* **Container** (25): isolated process using the host kernel, built from an image.
* **Context window** (6): maximum tokens a model can handle in a call.
* **Context engineering** (10): deciding what the model sees at each step.
* **Context variable (`contextvars`)** (13): per-task/request variable (request id) in async code.
* **Cookie attributes** (16): HttpOnly, Secure, SameSite, Path, Max-Age.
* **CORS** (16): browser rules for cross-origin reads, opted into by headers.
* **Cosine similarity** (5): angle-based similarity between vectors.
* **CRLF** (23): Windows line endings; can break shell scripts.
* **CSP** (19, 21): Content-Security-Policy header restricting resource origins.
* **CSPRNG** (20): cryptographically secure random generator (`secrets`).
* **CSRF** (16): forged cross-site request using auto-sent cookies.
* **Credit (search)** (14): one paid SerpAPI call; capped per user and globally **(repo)**.

**D**

* **DAG** (3): directed acyclic graph; basis of topological sort.
* **Data fiduciary / principal** (21): DPDP Act roles (organisation / individual).
* **Dead-letter queue** (30): where undeliverable messages go.
* **Decoy (test)** (11): wrong-but-tempting test data that exposes a skipped check **(repo)**.
* **Defence in depth** (20): multiple independent security layers.
* **Demo mode** (12): `BACKEND_MODE=demo`: scripted model + mock search; refused in prod **(repo)**.
* **Dependency injection** (2): passing collaborators in rather than constructing them inside.
* **Digest (image)** (25): immutable content hash of an image.
* **DNS / TTL / rebinding** (16): name resolution, cache lifetime, and the attack switching answers.
* **DORA metrics** (28): deployment frequency, lead time, change failure rate, time to restore.
* **DPDP Act** (21): India's Digital Personal Data Protection Act, 2023.
* **DPA (data processing agreement)** (15, 21): contract governing a processor's use of personal data.
* **Dynamic programming** (4): solving overlapping subproblems by storing results.

**E**

* **Embedding** (5, 10): vector representing meaning of text/image.
* **Entropy** (5, 20): measure of uncertainty/randomness (bits).
* **Environment variable / env file** (1b, 26): runtime configuration / `NAME=value` file.
* **Error budget** (13, 28): allowed unreliability (1 − SLO).
* **Eval** (12): test for probabilistic behaviour of an AI system.
* **Event loop** (2): single-threaded scheduler running coroutines/callbacks.
* **Exec form (Docker)** (25): `CMD ["prog", "arg"]`; signals reach the process.
* **Expand/contract** (17, 28): backward-compatible migration pattern.

**F**

* **Fail closed / fail open** (20): deny vs allow when a control cannot decide.
* **Few-shot prompting** (7): examples in the prompt.
* **Fine-tuning / LoRA** (6): continuing training on your data / low-rank adapters.
* **Fixture (test)** (29): reusable test setup, or recorded real data.
* **Forward Deployed Engineer** (33): engineer embedded with customers to ship solutions.
* **Function calling** (8): model requests structured tool calls; code executes.

**G**

* **Gate (eval)** (12): hard guarantee that must be 1.0 for every case **(repo)**.
* **Gateway (LLM)** (15, 31): proxy providing routing, caching, quotas, fallback for models.
* **GIL** (2): CPython lock allowing one thread to run bytecode at a time.
* **Graceful shutdown** (18): finish in-flight work on SIGTERM before exiting.
* **Greedy algorithm** (4): locally best choices; correct only with a greedy-choice property.
* **Guardrail** (11): input/output/action control around a model.

**H**

* **Hallucination** (6): confident but false model output.
* **Hash chain** (3, 22): entries each containing the previous entry's hash.
* **Hash table** (3): O(1) average key-value structure.
* **Health check** (25, 26): endpoint/command reporting readiness (`/health`).
* **Heap / priority queue** (3): structure giving the min/max element first.
* **HMAC** (20): keyed hash for integrity and authenticity.
* **HNSW** (5, 10): layered proximity-graph ANN index.
* **HSTS** (16, 27): header forcing HTTPS for a period.
* **HTTP idempotent methods** (16): GET, HEAD, PUT, DELETE, OPTIONS.
* **Human-in-the-loop (HITL)** (9): a person is part of the workflow (interrupts).
* **Hybrid search** (10): dense + sparse retrieval fused (RRF).

**I**

* **Idempotency key** (11, 30): client-supplied id making retried writes safe.
* **IDOR** (21): accessing others' objects by id due to missing authorisation.
* **Image (Docker)** (25): layered, read-only template for containers.
* **Index (database)** (3, 17): structure speeding lookups; usually a B-tree.
* **Interrupt (LangGraph)** (9): pause point returning control until resumed **(repo)**.
* **Inverted index** (10): term → documents map.
* **IPv4/IPv6 stall** (16): ~40 s hang when IPv6 is advertised but broken **(repo workaround: `force_ipv4`)**.
* **Isolation level** (17): how much concurrent transactions see of each other.

**J**

* **Jitter** (4): randomness added to retry delays.
* **JSON Schema / JSON mode** (7): schema for structured output / syntactically valid JSON only.
* **JSON-RPC** (8): request/response protocol used by MCP.
* **JWT / JWS / JWKS / `jti`** (20): signed token; signature form; public-key set; unique token id.

**K**

* **K8s (Kubernetes)** (26): container orchestrator.
* **KV cache** (6): cached attention keys/values speeding generation.
* **KMS / HSM** (20): key management service / hardware security module.

**L**

* **LangChain / LangGraph** (9): LLM building blocks / stateful graph framework **(repo)**.
* **Layer (Docker)** (25): filesystem diff produced by one instruction.
* **Least privilege** (20): grant only needed power.
* **Leeway (JWT)** (20): small tolerance for clock skew **(repo: 10 s)**.
* **Lethal trifecta** (8, 21): private data + untrusted content + external communication.
* **Liveness / readiness probe** (26): restart-if-dead / send-traffic-if-ready checks.
* **Little's Law** (5): L = λW.
* **LLM-as-judge** (12): a model scoring outputs.
* **Load shedding** (30): rejecting excess work early.
* **Logit** (5, 6): raw score before softmax.
* **LRU** (3): least-recently-used eviction.

**M**

* **MCP** (8): Model Context Protocol for tools/resources/prompts **(repo)**.
* **Merkle tree** (3, 22): hash tree with O(log n) inclusion proofs.
* **Middleware** (18): code wrapping every request/response.
* **Migration** (17): versioned schema change **(repo: numbered SQL)**.
* **mTLS** (16, 20): TLS with client certificates.
* **Multi-stage build** (25): build in one stage, run from a clean final stage.
* **MVCC** (17): multi-version concurrency control in Postgres.

**N**

* **Namespace (Linux)** (23): isolates what a process can see.
* **NAT** (16): shared public address for private hosts.
* **`NEXT_PUBLIC_`** (19): Next.js variables inlined into browser code at build time.
* **Nines** (30): availability levels (99.9%, 99.99%).
* **no-new-privileges** (25): blocks privilege gain via setuid.
* **Normalisation (database / text)** (17, 3): reduce redundancy / canonicalise text.

**O**

* **OAuth 2.0 / OIDC / PKCE** (20): delegated authorisation / identity layer / code-interception protection.
* **Observability** (13): ability to ask new questions of a running system.
* **OpenTelemetry / OTLP** (13): telemetry standard / its wire protocol.
* **OpenRouter** (15): multi-model gateway used for the chat model **(repo)**.
* **Orchestrator** (26, 31): runs containers (Kubernetes) / runs the AI workflow.
* **OWASP Top 10** (21): web risk list; also a separate LLM Top 10.

**P**

* **p50/p95/p99** (5): latency percentiles.
* **PACELC** (30): CAP plus latency-vs-consistency trade-off without partitions.
* **Pepper / salt** (20): secret / per-item random value in password hashing.
* **PgBouncer** (17): Postgres connection pooler.
* **PID 1** (23, 25): first process in a container; must handle signals.
* **Pod / Deployment / Service / Ingress** (26): Kubernetes objects.
* **Prefill / decode** (6): processing the prompt / generating tokens.
* **Prefix caching (prompt caching)** (6, 14): discounted reuse of identical prompt prefixes.
* **Prometheus / PromQL** (13): metrics system / its query language.
* **Prompt injection** (21): instructions smuggled into model input.
* **Property-based testing** (29): testing invariants over generated inputs.
* **Pydantic** (2, 7): validation/serialisation library **(repo)**.

**Q–R**

* **Quantisation** (6): lower-precision weights for faster inference.
* **RAG** (10): retrieval-augmented generation.
* **Rate limiting (token bucket, sliding window)** (4, 30): controlling request rates.
* **Reasoning model** (6): model that thinks before answering.
* **Recall@k / MRR / nDCG** (10): retrieval metrics.
* **Reducer (LangGraph)** (9): merge function for state updates (`add_messages`).
* **Refresh token (rotation, family, reuse detection)** (20): long-lived revocable credential replaced on each use **(repo)**.
* **Replay protection** (20): refusing a second use of a token (`jti`) **(repo)**.
* **Residual risk** (21): risk remaining after controls.
* **REST / SSE / WebSocket** (16): API style / server push stream / bidirectional channel.
* **Reverse proxy** (16, 27): front door forwarding to internal services (Caddy) **(repo)**.
* **RPO / RTO** (17, 28): tolerable data loss / downtime.
* **RRF** (10): reciprocal rank fusion.
* **RS256 / HS256** (20): RSA / HMAC JWT signing algorithms.
* **Runbook** (13, 28): step-by-step response guide for an alert.

**S**

* **Saga / outbox** (30): distributed-transaction patterns.
* **SameSite** (16): cookie attribute limiting cross-site sending.
* **SBOM / SCA / SAST / DAST** (21): software bill of materials / dependency / static / dynamic scanning.
* **Schema versioning** (7, 8): `schema_version` in tool results **(repo)**.
* **Secrets manager** (20): store for credentials (Vault, cloud services).
* **SerpAPI** (15): search-results API (Google Shopping) **(repo)**.
* **Service discovery** (16, 26): finding services by name.
* **SLI / SLO / SLA** (13, 28): indicator / objective / contract.
* **Softmax / temperature / top-p / top-k** (5, 6): sampling math and controls.
* **SNI** (16): hostname sent in the TLS handshake.
* **Span / trace / `traceparent`** (13): unit of work / request path / W3C header.
* **SQL injection** (17, 21): data interpreted as SQL; prevent with parameters.
* **SSRF** (21): making a server fetch attacker-chosen URLs.
* **Stateless service** (30): holds no per-user state between requests.
* **Structured output** (7): schema-conforming model output.
* **STRIDE** (20): spoofing, tampering, repudiation, information disclosure, DoS, elevation.

**T**

* **Temperature** see Softmax.
* **Three-valued logic (match/mismatch/unknown)** (11, 17): verifier statuses **(repo)**.
* **Timeout (connect/read)** (11, 16): bounded wait for I/O.
* **TLS termination** (16, 27): decrypting HTTPS at the proxy.
* **Token (LLM)** (6): sub-word unit of text.
* **Tool server / tool call** (8): private MCP server / model-requested function.
* **Topological sort** (3, 4): ordering a DAG's nodes by dependencies.
* **Tool poisoning / rug pull** (8, 21): malicious or changing third-party tool descriptions.
* **Trie** (3): prefix tree.
* **Trust boundary** (20): where data/control crosses privilege levels.
* **TTL cache** (3): cache with expiry.
* **Twelve-factor app** (2): config in env, stateless processes, logs to stdout.

**U–Z**

* **Union-find** (3, 4): disjoint-set structure.
* **uv** (2, 25): fast Python package/project manager **(repo)**.
* **UUID** (17): 128-bit identifier; v4 random.
* **Vector database / pgvector** (10): storage for embeddings / Postgres extension.
* **Verifier** (11): deterministic check of products against the request **(repo)**.
* **Volume / bind mount / tmpfs** (25): persistent data / host path / in-memory dir.
* **WAF / CDN** (27): web application firewall / content delivery network.
* **WAL / PITR** (17): write-ahead log / point-in-time recovery.
* **Walking skeleton** (34): thinnest end-to-end slice built with fakes first.
* **Wilson interval** (5): confidence interval for a proportion.
* **Workflow (vs agent)** (9): code-defined sequence with model-filled steps.
* **WORM storage** (22): write-once-read-many (S3 Object Lock).
* **X-Forwarded-For** (16): header carrying the original client address through proxies.
* **XSS** (19, 21): script injection into a web page.
* **Zod** (2, 19): TypeScript runtime schema validator **(repo, Mastra)**.
