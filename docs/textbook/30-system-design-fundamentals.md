# Chapter 30. System Design Fundamentals

> **Learning objectives.** Use a repeatable framework to design systems in interviews and in real engagements; understand scalability, availability, consistency and the CAP/PACELC trade-offs; know the standard building blocks (load balancers, caches, databases, replication, sharding, queues, rate limiters, locks, IDs) and the reliability patterns around them; do back-of-the-envelope estimates; and compare architecture styles. Concepts are tied to this project's single-node design so Chapters 31-32 can scale it.
>
> **Prerequisites.** Chapters 3, 5, 16, 17, 26.

**System design** is the skill of choosing components and trade-offs so a system meets its requirements at a given scale. For an entry-level FDE interview, you are rarely expected to design Google; you are expected to **structure ambiguity, make explicit assumptions, reason about bottlenecks and failure, and communicate trade-offs**. On the job, the same skill decides whether your customer's pilot survives its first real traffic.

---

## 30.1 A framework you can use every time

1. **Clarify requirements** (5 minutes).
   * **Functional**: what must it do? (Users sign up, chat, get outfits, click Buy.)
   * **Non-functional**: scale (users, requests/sec), latency targets, availability, consistency needs, durability, security/privacy, cost, compliance, time-to-market.
   * **Out of scope**: say what you will *not* do.
2. **Estimate** (5 minutes): requests per second, storage, bandwidth, number of servers (Section 30.8).
3. **Define the API and the data model** (5-10 minutes): the main endpoints and entities; access patterns drive storage choices.
4. **Sketch a high-level design** (10 minutes): clients → edge → services → data, with a diagram.
5. **Deep-dive on the hard parts** (15 minutes): the bottleneck or the part the interviewer cares about (caching, sharding, consistency, streaming, AI cost).
6. **Identify bottlenecks, failure modes and trade-offs; evolve** (5 minutes): what breaks at 10x? What would you monitor?
7. **Summarise** and ask for feedback.

**Meta-rules:** think aloud; state assumptions ("I'll assume 1M daily users, 10% active at peak"); start simple (a monolith and one database) and add components only to answer a named problem; quantify; discuss *why not* alternatives; connect to operations (monitoring, deployment, security).

## 30.2 Core concepts

### Scalability

* **Vertical scaling (scale up)**: a bigger machine. Simple; has a ceiling and a single point of failure.
* **Horizontal scaling (scale out)**: more machines. Needs **stateless** services (any instance can serve any request), a load balancer, and shared state in stores (Chapter 26). It is the dominant strategy.
* **Stateless vs stateful**: keep application servers stateless (state in a database/cache) so you can add, remove or replace instances freely. *This app's one violation of statelessness is in-process memory used for rate limits, the replay guard, caches and the per-conversation lock* (Chapter 32).

### Performance terms

* **Latency**: time for one request (report percentiles: p50/p95/p99).
* **Throughput**: requests (or bytes) per second.
* **Bandwidth**, **concurrency**, **utilisation**, **queueing** (Little's Law: `L = λW`, Chapter 5).
* A system can have low latency and low throughput, or the reverse.

### Availability, reliability, durability

* **Availability**: fraction of time the service works. In "nines":

| Availability | Downtime per year | per month |
|---|---|---|
| 99% (two nines) | ~3.65 days | ~7.3 h |
| 99.9% | ~8.8 h | ~43.8 min |
| 99.99% | ~52.6 min | ~4.4 min |
| 99.999% | ~5.3 min | ~26 s |

  Availability of components **in series multiplies** (A × B); components **in parallel** (redundant) combine as `1 - (1-A)(1-B)`. Two 99% instances in parallel give 99.99%. Remember the load balancer, DNS, database and every dependency are in the chain.
* **Reliability**: correct operation over time (MTBF, MTTR; designing for MTTR is often better than for MTBF).
* **Durability**: committed data is not lost (replication, backups, fsync).
* **Fault tolerance** and **graceful degradation**: continue (possibly reduced) service despite failures.

### Consistency, CAP and PACELC

In a **distributed data store** during a **network partition (P)** you must choose between **Consistency (C)**: every read sees the latest write, and **Availability (A)**: every request gets a (maybe stale) answer. **CAP** says you cannot have all three when a partition occurs. Real systems are *tunable*. **PACELC** adds: *Else* (no partition), you still trade **Latency vs Consistency**.

Consistency models, from strongest: **linearizable** (behaves like one copy), **sequential**, **causal** (cause precedes effect), **read-your-writes** (you see your own updates), **monotonic reads**, **eventual** (replicas converge if writes stop). Choose per feature: a bank balance needs strong; a "likes" counter tolerates eventual; *a user must see the conversation they just wrote* (read-your-writes) even if the global feed is eventually consistent.

**ACID vs BASE**: single-node relational transactions (Chapter 17) vs distributed, eventually consistent designs.

### SLA, SLO, SLI

Contracted vs targeted vs measured reliability (Chapters 13 and 28).

## 30.3 Building blocks

### Load balancing

Distributes requests across instances; health checks; algorithms (round robin, least connections, consistent hashing, weighted); L4 vs L7; TLS termination; **sticky sessions** (avoid when possible; they hinder scaling and failover). Redundant load balancers (managed ones are redundant by design). **DNS round robin** and **global load balancing/anycast** for multi-region.

### Caching

A cache stores computed or fetched data closer/faster to avoid repeating work. Layers: **browser**, **CDN/edge**, **reverse proxy**, **application** (in-process or Redis/Memcached), **database buffer cache**.

**Patterns**

| Pattern | Read | Write | Notes |
|---|---|---|---|
| **Cache-aside (lazy)** | app checks cache; on miss loads from DB and fills cache | app writes DB, then invalidates/updates cache | most common; this repo's search cache is cache-aside |
| **Read-through** | cache itself loads on miss | | simpler apps, library-managed |
| **Write-through** | | write to cache and DB synchronously | consistent, slower writes |
| **Write-back (behind)** | | write to cache, flush to DB asynchronously | fast; risk of data loss |
| **Refresh-ahead** | proactively refresh hot entries | | avoids latency spikes |

**Hard problems:** **invalidation** ("there are only two hard things..."): use TTLs, versioned keys, explicit invalidation on writes; **stampede / thundering herd** (a popular entry expires and thousands of requests hit the database at once): request coalescing ("single flight"), jittered TTLs, locks, stale-while-revalidate; **hot keys**; **cache penetration** (queries for non-existent keys bypass the cache: cache negatives briefly, Bloom filters); **consistency** between cache and DB; **eviction policy** (LRU/LFU/TTL; Chapter 3); **memory bounds**; **security** (never cache per-user data under a shared key: tenant-partition keys).

*In this app*: the MCP server's in-process **TTL caches** (searches 6 h, product refs, links) are cache-aside with a bound; cache hits save a paid credit. Scaling out requires **Redis** for a *shared* cache, otherwise each instance has its own and the hit rate (and credit savings) drops.

### Databases at scale

* **Vertical first**: indexes, query tuning, more RAM, connection pooling (cheap and effective).
* **Read replicas**: a leader accepts writes; followers replicate (asynchronously) and serve reads. Watch **replication lag** (stale reads; use "read from leader after a write" for read-your-writes).
* **Partitioning (sharding)**: split data across nodes by a **shard key**.
  * **Range** (user ids 1-1M on shard A): simple; risk of hotspots.
  * **Hash** (`hash(user_id) % N`): even distribution; resharding moves lots of data (fix with **consistent hashing**).
  * **Directory/lookup**: a mapping service decides.
  * Choose a key matching access patterns (**per-user data → user id**); cross-shard queries/joins/transactions become hard; avoid sharding until you must.
* **Replication topologies**: leader-follower, multi-leader (conflict resolution), leaderless/quorum (Dynamo-style: `R + W > N` for read-your-writes).
* **Distributed transactions**: **two-phase commit** (blocking, fragile), **sagas** (a sequence of local transactions with compensating actions), **idempotent** operations and the **outbox pattern**.
* **Choose a store by access pattern** (Chapter 17's table). Start with Postgres.

**Consistent hashing** (to add/remove nodes while moving only ~1/N of keys):

```python
import bisect, hashlib

class Ring:
    def __init__(self, nodes, vnodes=100):
        self._ring = sorted((self._h(f"{n}#{i}"), n) for n in nodes for i in range(vnodes))
        self._keys = [k for k, _ in self._ring]
    @staticmethod
    def _h(s): return int(hashlib.md5(s.encode()).hexdigest(), 16)
    def node_for(self, key: str):
        i = bisect.bisect(self._keys, self._h(key)) % len(self._ring)    # next node clockwise on the ring
        return self._ring[i][1]
```

Virtual nodes smooth the distribution. Used in caches (memcached clients), Dynamo-style stores, CDNs.

### Queues, streams and asynchronous processing

* A **message queue** (SQS, RabbitMQ, Redis streams) decouples producers from consumers; **a stream/log** (Kafka, Kinesis, Pulsar) keeps an ordered, replayable record.
* Uses: **smoothing bursts** (queue-based load leveling), **background jobs** (image generation, emails, embeddings), **fan-out**, **retries**, **event-driven** integration.
* **Delivery semantics**: at-most-once, **at-least-once** (the practical default: **consumers must be idempotent**), exactly-once (only within limited systems, via idempotence + transactions).
* **Ordering** (per partition/key), **partitions and consumer groups**, **dead-letter queues** for poison messages, **backpressure**, **visibility timeouts**.
* **Job tables in Postgres** (`FOR UPDATE SKIP LOCKED`) are a perfectly good queue at modest scale.
* **When to go async**: the work is slow (seconds), failure-prone, or not needed to answer the user now. *The "try it on me" image feature belongs here (Chapter 18).*

### Rate limiting and load shedding

**Algorithms** (Chapter 4 has code for two):

| Algorithm | Idea | Pros | Cons |
|---|---|---|---|
| **Fixed window counter** | count per time bucket | trivial, O(1) | boundary burst (2× limit across a boundary) |
| **Sliding window log** | keep timestamps (this repo) | exact | O(limit) memory per key |
| **Sliding window counter** | weighted blend of current and previous window | approximate, O(1) | slight inexactness |
| **Token bucket** | refill rate + burst capacity | allows bursts, O(1) | parameters to tune |
| **Leaky bucket** | constant outflow queue | smooths traffic | adds queueing delay |

**Where**: edge/CDN, API gateway, per-service, per-user, per-IP, per-API-key, per-tenant, per-endpoint cost class. **Distributed**: central store with **atomic** operations (Redis `INCR` + `EXPIRE`, sorted sets, or a Lua script) so all instances share counters:

```python
def allow(r, key: str, limit: int, window_s: int) -> bool:          # fixed window in Redis (needs Redis 7 for EXPIRE ... NX)
    pipe = r.pipeline()
    pipe.incr(key); pipe.expire(key, window_s, nx=True)
    count, _ = pipe.execute()
    return count <= limit

def allow_sliding_log(r, key, limit, window_s):                      # exact sliding window with a sorted set
    now = time.time(); pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, now - window_s)
    pipe.zadd(key, {uuid.uuid4().hex: now})
    pipe.zcard(key); pipe.expire(key, window_s)
    _, _, count, _ = pipe.execute()
    return count <= limit
```

Respond with **429 + `Retry-After`**; **fail open or closed** if the limiter store is down (security-critical limits: closed; convenience limits: open); **limit by cost** (a chat turn costs more than a health check); **limits as a security control** (login lockout, credit caps) and a **fairness control** (one noisy tenant cannot starve others).

### Distributed coordination

* **Locks and leader election**: via ZooKeeper/etcd/Consul, or database advisory locks (`pg_advisory_lock`) for modest needs. **Fencing tokens** protect against a paused client that wakes up still believing it holds the lock.
* **Idempotency keys** to make retried writes safe.
* **Unique ID generation**: UUIDv4 (random, no coordination), **UUIDv7/ULID** (time-ordered: better index locality), **Snowflake-style** ids (timestamp + machine + sequence), database sequences.
* **Clocks**: never assume synchronised clocks; use logical clocks/versions where order matters (this is also why JWT validation has a leeway).
* **Service discovery**: DNS names, Kubernetes services, Consul.

### Search, blobs, CDN

* **Search**: inverted indexes (Elasticsearch/OpenSearch, Postgres FTS) (Chapter 10).
* **Blob/object storage** for large unstructured data (images, documents, backups); keep metadata in the DB, bytes in S3-like stores, serve through CDN with signed URLs.
* **CDN** for static and cacheable content.

### API gateway and BFF

A gateway centralises auth, rate limiting, routing and observability for many services; a **Backend-For-Frontend** shapes APIs for a specific client. *This project's planned "Mastra gateway" was a BFF idea that was dropped: the UI calls the API directly, and Caddy is the (minimal) edge.*

## 30.4 Reliability patterns (recap and extension of Chapter 11)

| Pattern | Problem it solves |
|---|---|
| **Timeouts** | a slow dependency must not hold resources forever |
| **Retries with backoff + jitter** | transient failures; avoid synchronised retry storms |
| **Idempotency** | retries and duplicates are safe |
| **Circuit breaker** | stop hammering a failing dependency; fail fast; recover gradually |
| **Bulkhead** | isolate resource pools so one failing dependency does not starve everything |
| **Load shedding / backpressure** | refuse excess work early (429/503) instead of collapsing |
| **Graceful degradation / fallbacks** | serve cached or reduced results |
| **Redundancy and failover** | survive instance/AZ failure |
| **Health checks and self-healing** | detect and replace bad instances |
| **Queue-based load leveling** | absorb spikes asynchronously |
| **Hedged requests** | cut tail latency for idempotent reads |
| **Canary and progressive delivery** | limit the blast radius of changes |
| **Chaos/game days** | verify that all the above actually work |

## 30.5 Architecture styles

| Style | Description | Fits | Watch out |
|---|---|---|---|
| **Monolith** | one deployable | small teams, early products | tangled code if undisciplined |
| **Modular monolith** | one deployable, strong internal module boundaries | most products for a long time | needs discipline |
| **Microservices** | many independently deployable services | large orgs, independent scaling/teams | distributed-systems complexity: network failures, versioning, observability, data consistency, operations cost |
| **Serverless/FaaS** | functions per request/event | spiky, event-driven workloads | cold starts, timeouts, state, vendor lock-in |
| **Event-driven** | components communicate by events | decoupling, integrations | eventual consistency, debugging |
| **Layered / hexagonal** | domain core with adapters | testability | over-abstraction |

**This project** is a **modular monolith plus one deliberately separate service**: the API (routes, accounts, agent, persistence) is one deployable; the tool server is separate **for a security reason** (a distinct privilege boundary with no public address), not for scale. That is the right way to justify a split: *by a boundary you can state* (security, scaling profile, team ownership, release cadence, technology), not by fashion. **"Don't distribute until you must": every network hop adds latency, failure modes and operational cost.**

## 30.6 Data modelling by access pattern

Ask: **what are the read and write patterns?** Reads:writes ratio? Point lookups vs scans vs aggregations? Latency needs? Consistency needs? Growth rate?

* **Per-user, small, transactional data** → relational (Postgres).
* **Key-value lookups at huge scale** → DynamoDB/Redis.
* **Time series/metrics** → TSDB.
* **Full-text/faceted search** → search engine.
* **Analytics over large history** → columnar warehouse.
* **Relationship traversal** → graph DB.
* **Blobs** → object store.

Polyglot persistence is common but **each store is operational weight**: prefer one general-purpose database until a specific requirement forces another.

## 30.7 Security and privacy as design inputs

Include in every design: authentication/authorisation model, trust boundaries and network exposure, secrets handling, encryption in transit and at rest, input validation, abuse and cost controls, audit logging, data retention and deletion, compliance (Chapters 20-22). **Security requirements change architecture** (this app's private tool server; the single public door).

## 30.8 Back-of-the-envelope estimation

### Handy numbers

* 1 day ≈ 86,400 s ≈ **10⁵ s**. 1 month ≈ 2.6 × 10⁶ s. 1 year ≈ 3.15 × 10⁷ s.
* **Powers of two**: 2¹⁰ ≈ 1 thousand, 2²⁰ ≈ 1 million, 2³⁰ ≈ 1 billion; KB/MB/GB/TB = 10³/10⁶/10⁹/10¹² bytes.
* Peak traffic ≈ **2-5×** average. Read:write ratios (100:1 for many web apps).
* Latency (Chapter 5): memory ~100 ns; SSD ~100 µs; same-DC round trip ~0.5 ms; cross-continent ~100+ ms; LLM call seconds.
* Single commodity server: tens of thousands of simple requests/s for a well-tuned async service; a few thousand DB transactions/s; a Postgres instance comfortably handles millions of rows and thousands of QPS with indexes. **Measure; do not guess**.

### Worked example: capacity for AI Stylist

Assumptions: **50,000 monthly active users**, each starts **4 conversations/month** (200,000 conversations/month). A conversation = **2 turns** (first message, then style pick). A planning turn takes **~30 s** and holds a worker thread.

* Conversations/day ≈ 200,000 / 30 ≈ **6,700/day** ≈ 0.08/s average. Assume peak = 5× average and a concentrated 4-hour evening window: if 60% of daily traffic falls in 4 hours (14,400 s): 4,000 / 14,400 ≈ **0.28 conversations/s**, so about **0.28 planning turns/s** at peak (each conversation has one heavy turn).
* **Little's Law**: concurrent heavy turns `L = λ W = 0.28 × 30 ≈ 8.4`. So **~9 concurrent turns at peak**, comfortably within one process's thread pool (about 40) but it shows how quickly it scales: at 10× growth, **~84** concurrent turns means 3+ processes.
* **Search credits/day**: 6,700 conversations × 8 searches × (1 − 0.4 cache hit) ≈ **32,000 credits/day**; at any realistic per-credit price this dwarfs model cost (Chapter 14) and breaks a small plan: *the external API quota, not the servers, is the scaling limit.*
* **Model calls/day**: 6,700 × ~4 ≈ 27,000 calls/day ≈ 0.3/s average; peak ~1.5/s: far below paid-tier limits, far above the free tier's 50/day.
* **Database writes**: per conversation ≈ 1 conversation row + 4 outfits + 8 items + ~6 audit rows + checkpoint writes (each graph step writes checkpoint rows; assume ~30): **~50 rows**, so 6,700 × 50 ≈ 335,000 rows/day ≈ **4 rows/s**: trivial for Postgres. **Storage**: checkpoints may hold ~10-20 KB per conversation (messages + outfit data); 6,700 × 15 KB ≈ **100 MB/day ≈ 3 GB/month**: manageable; plan retention.
* **Bandwidth**: SSE events are small (a few KB); outfit payloads ~10 KB; images are served by retailers' CDNs, not by us: **negligible for our servers**.

Conclusion you would state: *one modest server suffices for the compute; the bottlenecks are (1) search API cost/quota, (2) per-process in-memory state when we add instances for availability, (3) the model provider's rate limits, (4) conversation-state growth.*

## 30.9 Three classic designs, briefly (practice)

### URL shortener

* **Requirements**: create short URL, redirect fast, analytics optional; read:write ≈ 100:1; links last years.
* **API**: `POST /shorten {url}` → `{code}`; `GET /{code}` → `301/302`.
* **ID generation**: 7 base-62 chars = 3.5 trillion codes. Options: counter + base62 encode (needs coordination; shard counters in ranges), random with collision check, hash of URL (+ salt).
* **Storage**: key-value (`code → url`), tiny rows; **cache** hot codes (Redis/CDN); **replicate** reads.
* **Redirect type**: 301 (cacheable; fewer hits to you, loses analytics) vs 302.
* **Abuse**: validate URLs, block malicious domains, rate limit creation, **SSRF/phishing** care.
* **Scale**: reads dominate → cache + replicas; shard by code hash.

### Rate limiter service

* **Requirements**: limit by user/IP/API key, low latency, accurate enough, distributed.
* **Algorithm**: token bucket or sliding window counter; **store**: Redis with atomic Lua/INCR; **placement**: gateway or middleware; **failure mode**: fail open for convenience limits; **config** per route/tier; **headers**; **observability** of rejections; **hot keys** and clock skew (use Redis time).

### Chat system (real-time)

* **Requirements**: 1:1 and group messages, delivery guarantees, history, presence.
* **Transport**: WebSocket (or SSE + POST); **stateful connection servers** behind a load balancer; a **connection registry** (user → server) in Redis; **pub/sub or a message bus** routes messages to the server holding the recipient connection; **persistence** in a store partitioned by conversation id; **offline delivery** via a queue and push notifications; **ordering** per conversation (sequence numbers); **idempotency** via message ids; **scale** by sharding conversations.

## 30.10 Communicating a design

* Draw boxes and arrows; label protocols and data stores; number the request flow.
* Say the numbers you assumed.
* For every component say *why it is there* and *what you would do without it*.
* Name failure modes and mitigations unprompted.
* Offer an **MVP** and an **evolution path** ("single node first; then Redis for shared state; then read replicas").
* When challenged, **trade-off, do not defend**: "that costs us X but buys Y; if Z matters more, I would instead..."

## Common mistakes

* Starting with microservices and Kubernetes for a 100-user product.
* No numbers.
* Ignoring failure and operations.
* Treating the database as infinitely scalable or unbreakable.
* Adding a cache without an invalidation story.
* Stateful servers that cannot be scaled or replaced.
* Not stating consistency requirements per feature.
* Over-engineering for 1000× scale.

## Summary

* Use a framework: requirements → estimates → API/data → high-level design → deep dives → bottlenecks and trade-offs.
* Scale out with stateless services, shared state stores, caches, replicas, queues; shard only when necessary.
* Understand availability math, CAP/PACELC and consistency models; pick per feature.
* Rate limiting, idempotency, timeouts, retries, circuit breakers, bulkheads, load shedding and graceful degradation are the vocabulary of reliability.
* Estimate with simple arithmetic; here the *external API quota* and *in-process state* are the real limits, not CPU.
* Justify service splits by boundaries (security, scaling, ownership), not fashion.

## Key terms

*horizontal/vertical scaling, stateless, availability (nines), consistency, CAP, PACELC, read-your-writes, cache-aside, stampede, replication lag, sharding, consistent hashing, two-phase commit, saga, outbox, at-least-once, idempotency key, token bucket, circuit breaker, bulkhead, backpressure, modular monolith, Little's Law.*

## Interview questions

1. Walk through designing a URL shortener (or rate limiter) end to end.
2. How do you scale a read-heavy web service? A write-heavy one?
3. Explain CAP and give a feature where you would choose availability and one where consistency.
4. What is a cache stampede and how do you prevent it?
5. How does consistent hashing work and why is it used?
6. How would you make an API that triggers a slow job reliable and idempotent?
7. Compute availability for a service with a load balancer (99.99%) in front of two instances (99% each) and a database (99.9%).
8. Estimate the load and servers for 1M daily active users sending 10 requests each.

## Exercises

1. Do the capacity estimate for AI Stylist with your own assumptions and identify the first bottleneck.
2. Implement the Redis sliding-log limiter and test with two simulated API instances sharing it.
3. Implement consistent hashing and measure key movement when adding a node.
4. Design (on paper) a notification system: requirements, API, queue design, retry/idempotency, scaling, failure modes.
5. Draw this app's architecture and mark every single point of failure.
