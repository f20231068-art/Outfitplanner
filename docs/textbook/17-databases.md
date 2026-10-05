# Chapter 17. Databases

> **Learning objectives.** Model data relationally; write SQL fluently (joins, aggregation, CTEs, window functions, NULL semantics); understand transactions, ACID, isolation, locks and MVCC; design and read indexes with `EXPLAIN`; manage migrations, pools and backups; know when to use Redis, vector, document or analytical stores; secure a database; and read every table, index, trigger and query in this repo with full understanding.
>
> **Prerequisites.** Chapters 2-3 (hash tables, B-trees).

Almost every real AI product is, underneath, a database application. Sessions, users, conversations, results, audit trails, usage metering, evaluation data, embeddings: all are data with integrity, concurrency and recovery requirements. An FDE who is strong at databases debugs half of production problems faster than peers.

---

## 17.1 The relational model

A **relational database** stores data in **tables** (relations): each **row** is a record, each **column** has a type. Rows are linked by **keys**:

* **Primary key (PK)**: uniquely identifies a row (`users.id`).
* **Foreign key (FK)**: a column referencing another table's key (`conversations.user_id → users.id`), enforced by the database so you cannot have an orphan.
* **Unique constraint**: no two rows share the value (`token_hash`, and `lower(email)`).
* **Check constraint**: a rule on a row (`total_inr > 0`, `confidence IN ('high','low')`).
* **Not null / default**: required values and automatic ones.

**Why bother with constraints?** *Put invariants in the database, not only in application code.* Application bugs, scripts, other services and manual fixes all bypass your Python; the database does not. Look at what `001_init.sql` forbids by itself: negative prices, an outfit item that is neither top nor bottom, two items in the same slot, duplicate outfit positions, duplicate emails differing only by case, and updates or deletes of audit rows.

### Normalisation (and when to break it)

**Normal forms** reduce redundancy and update anomalies:

* **1NF**: atomic values (no lists in a column); each row identified.
* **2NF**: no partial dependence on part of a composite key.
* **3NF**: non-key columns depend only on the key (not on other non-key columns).

Practical version: *store each fact once; reference it by key.* `outfits` and `outfit_items` are split (an outfit has exactly two items), not a wide row with `top_title, bottom_title, ...`. But normalisation has a price (joins), so **denormalise deliberately** when reads dominate: the `outfits` row keeps `total_inr` and `confidence` even though they could be derived from items; `conversations.title` is stored although derivable from the first message. Document why.

**JSONB** (Postgres) is the pressure valve for semi-structured data: `outfit_items.verification jsonb NOT NULL` stores the whole requested-vs-found report "kept as evidence". Use it for data you store and show rather than filter and join on; promote fields to real columns when you start querying them.

## 17.2 The schema in this repo, table by table

```
users ──< refresh_tokens
  │
  └──< conversations ──< outfits ──< outfit_items
  │                         ▲
  └─────────────────────────┘ (outfits also store user_id directly)

audit_log (append-only, hash-chained; actor is a user id or 'system', not an FK)
schema_migrations (which numbered migrations were applied)
+ LangGraph checkpoint tables (created by the library: checkpoints, blobs, writes ...)
```

### `users`

```sql
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text        NOT NULL,
    password_hash text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    disabled_at   timestamptz,
    CONSTRAINT users_email_shape CHECK (position('@' in email) > 1 AND length(email) <= 254)
);
CREATE UNIQUE INDEX users_email_lower_idx ON users (lower(email));
```

* **UUID primary keys** (`gen_random_uuid()`): not guessable or enumerable (unlike `1, 2, 3...`, which leak counts and invite id-guessing), safe to generate in many places, and mergeable across systems. Cost: larger and random (index locality), fine here.
* **Only the Argon2id hash is stored**, never the password (Chapter 20).
* **`timestamptz`** (timestamp *with* time zone): stores an absolute instant (UTC internally). Use it for *every* time column; `timestamp` without time zone is a bug magnet.
* **`disabled_at` instead of deleting**: soft-disable locks an account while keeping history (and foreign keys). Soft deletion has its own costs (queries must filter `disabled_at IS NULL`, as `get_user` does).
* **Case-insensitive uniqueness** by indexing the *expression* `lower(email)`: `A@x.com` and `a@x.com` are the same person. The query must use the same expression (`WHERE lower(email) = %s`) to use the index.
* The `CHECK` is a cheap backstop; real validation happens in Python (`normalize_email`).

### `refresh_tokens`

```sql
CREATE TABLE refresh_tokens (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    family_id uuid NOT NULL,
    token_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz,
    revoked_at timestamptz
);
CREATE INDEX refresh_tokens_user_idx   ON refresh_tokens (user_id);
CREATE INDEX refresh_tokens_family_idx ON refresh_tokens (family_id);
```

* Only the **SHA-256 of the token** is stored: a stolen database cannot be used to log in.
* **`family_id`** groups every token descended from one login; theft detection revokes the whole family (`UPDATE ... WHERE family_id = ...`, which uses `refresh_tokens_family_idx`).
* **`ON DELETE CASCADE`**: deleting a user deletes their tokens (also conversations, outfits). Cascades are convenient and dangerous: know what a `DELETE FROM users` will remove (right-to-erasure requests rely on this).
* `used_at` and `revoked_at` are *state as timestamps* (when, not just whether), invaluable for audits.
* `token_hash UNIQUE` creates an index, so `WHERE token_hash = ...` (every refresh) is O(log n).

### `conversations`

```sql
CREATE TABLE conversations (id uuid PK, user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    title text NOT NULL DEFAULT 'New conversation', created_at ..., updated_at ...);
CREATE INDEX conversations_user_recent_idx ON conversations (user_id, updated_at DESC);
```

The **LangGraph thread id is this row's id**. The composite index serves the hot query "this user's most recent conversations" (`WHERE user_id = ? ORDER BY updated_at DESC LIMIT 30`) *without a sort step*: the index is already ordered.

### `outfits` and `outfit_items`

```sql
CREATE TABLE outfits (
    id uuid PK, conversation_id uuid NOT NULL REFERENCES conversations ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    batch integer NOT NULL DEFAULT 1, position smallint NOT NULL CHECK (position >= 1),
    style_name text NOT NULL, total_inr integer NOT NULL CHECK (total_inr > 0),
    confidence text NOT NULL CHECK (confidence IN ('high', 'low')), rationale text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, batch, position)
);
CREATE TABLE outfit_items (
    id uuid PK, outfit_id uuid NOT NULL REFERENCES outfits ON DELETE CASCADE,
    slot text NOT NULL CHECK (slot IN ('top', 'bottom')), product_id text, title text NOT NULL,
    retailer text NOT NULL, price_inr integer NOT NULL CHECK (price_inr >= 0), mrp_inr integer,
    url text NOT NULL, url_kind text, image_url text NOT NULL, verification jsonb NOT NULL,
    UNIQUE (outfit_id, slot)
);
CREATE INDEX outfit_items_product_idx ON outfit_items (product_id);
```

* **Money as integers** (`price_inr integer`, whole rupees). Never store money in floating point (`0.1 + 0.2 != 0.3`). For currencies with minor units use integer paise/cents or `numeric`.
* **`batch`** is a round of four outfits within a conversation; **`UNIQUE (conversation_id, batch, position)`** guarantees no duplicate positions, and doubles as an **idempotency guard**.
* **`outfits.user_id`** is a deliberate **denormalisation**: it lets ownership checks (`user_owns_product`) and "recent outfits for a user" skip a join through `conversations`. The cost: it must stay consistent (set from the same authenticated user, enforced by code).
* **`product_id` index**: "does this product belong to one of this user's outfits?" runs before *every* buy-link request: `SELECT ... FROM outfit_items i JOIN outfits o ... WHERE o.user_id = %s AND i.product_id = %s`.
* **`CHECK ... IN (...)` instead of a Postgres `ENUM`**: easier to change later (altering enums is clumsy).
* `UNIQUE (outfit_id, slot)`: an outfit has exactly one top and one bottom.

### `audit_log` (append-only, hash-chained)

```sql
CREATE TABLE audit_log (
    id bigserial PRIMARY KEY, ts timestamptz NOT NULL, actor text NOT NULL, action text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}', prev_hash text NOT NULL, hash text NOT NULL UNIQUE
);
CREATE FUNCTION audit_log_is_append_only() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP; END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();
CREATE TRIGGER audit_log_no_truncate BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only();
```

* **`bigserial`** gives a monotonically increasing id used to order the chain.
* **Triggers** run inside the database and *refuse* `UPDATE`, `DELETE` and `TRUNCATE`: a guard that holds even if application code is compromised. A **database owner can drop the triggers**, which is why the hash chain exists as a second, independent, detectable layer (Chapter 22).
* `actor` is `text` (a user id **or** `'system'`/`'anonymous'`), deliberately **not a foreign key**: the log must survive user deletion, and it must record events by actors that are not users.

## 17.3 SQL you must know

### Core queries

```sql
-- read
SELECT id, title, updated_at FROM conversations
WHERE user_id = $1 ORDER BY updated_at DESC LIMIT 30;

-- joins
SELECT o.id, o.style_name, i.slot, i.title, i.price_inr
FROM outfits o
JOIN outfit_items i ON i.outfit_id = o.id          -- INNER JOIN: only matching rows
WHERE o.conversation_id = $1
ORDER BY o.batch, o.position;

-- aggregation
SELECT style_name, count(*) AS n, round(avg(total_inr)) AS avg_total
FROM outfits GROUP BY style_name HAVING count(*) >= 5 ORDER BY n DESC;

-- insert returning the generated id (used everywhere in repo.py)
INSERT INTO conversations (user_id) VALUES ($1) RETURNING id, title, created_at;

-- upsert
INSERT INTO counters (k, n) VALUES ('x', 1)
ON CONFLICT (k) DO UPDATE SET n = counters.n + 1;
```

### Join types

`INNER JOIN` (matches only), `LEFT JOIN` (all left rows, nulls where no match), `RIGHT`, `FULL OUTER`, `CROSS` (every combination). Know that `LEFT JOIN ... WHERE right.col = x` accidentally becomes an inner join (filter in `ON` instead).

### CTEs and window functions

```sql
-- CTE: name a sub-result
WITH recent AS (
  SELECT * FROM outfits WHERE created_at > now() - interval '7 days'
)
SELECT user_id, count(*) FROM recent GROUP BY user_id;

-- window function: rank within each group without collapsing rows
SELECT user_id, id, total_inr,
       rank() OVER (PARTITION BY user_id ORDER BY total_inr DESC) AS price_rank
FROM outfits;

-- running total / previous row
SELECT ts, action, count(*) OVER (ORDER BY ts) AS running_events,
       lag(hash) OVER (ORDER BY id) AS previous_hash
FROM audit_log;
```

(`lag(hash) OVER (ORDER BY id)` is, in SQL, the chain-verification idea: compare each row's `prev_hash` with the previous row's `hash`. A one-query integrity check: `SELECT id FROM (SELECT id, prev_hash, lag(hash) OVER (ORDER BY id) AS expected FROM audit_log) t WHERE expected IS NOT NULL AND prev_hash <> expected;`.)

### NULL: three-valued logic again

`NULL` means "unknown". `NULL = NULL` is **NULL** (not true); use `IS NULL` / `IS NOT NULL` (the repo: `disabled_at IS NULL`, `revoked_at IS NULL`). `WHERE x <> 5` excludes rows where `x` is NULL. `COUNT(col)` ignores NULLs, `COUNT(*)` does not. `NOT IN (subquery containing NULL)` returns nothing (use `NOT EXISTS`). Chapter 11's `match/mismatch/unknown` is the same idea.

### SQL injection and parameters (non-negotiable)

**Never build SQL by concatenating strings with user data.** Use **parameters**: the driver sends the query and the values separately, so data can never become code.

```python
conn.execute("SELECT id FROM users WHERE lower(email) = %s", (email,))        # SAFE: %s is a parameter placeholder
conn.execute(f"SELECT id FROM users WHERE email = '{email}'")                 # VULNERABLE: ' OR '1'='1
```

Placeholders cannot be used for **identifiers** (table or database names); use `psycopg.sql.Identifier` (as `tests/conftest.py` does when creating throwaway databases). All of `repo.py` is parameterised; so is every other query in the codebase.

### N+1 queries

Fetching a list, then querying once per row, produces N+1 queries (slow). `repo.outfits_for_conversation` fetches outfits with their items in **one joined query** and groups in Python: constant query count regardless of the number of outfits.

### Pagination

`OFFSET n LIMIT m` is simple but slow for deep pages (the database still scans past n rows) and unstable when data changes. **Keyset pagination** (`WHERE (updated_at, id) < ($last_updated, $last_id) ORDER BY updated_at DESC, id DESC LIMIT m`) is efficient and stable. `list_conversations` caps at 30; real pagination would use keyset.

## 17.4 Transactions, ACID, isolation and locks

A **transaction** groups statements into one all-or-nothing unit. **ACID**:

* **Atomicity**: all or none. (`save_outfits` inserts four outfits and eight items together or not at all.)
* **Consistency**: constraints hold before and after.
* **Isolation**: concurrent transactions do not see each other's partial work (to a degree set by the isolation level).
* **Durability**: once committed, it survives a crash (write-ahead log fsynced to disk).

### How the code uses transactions (psycopg 3 + pool)

```python
with request.app.state.pool.connection() as conn:     # borrow a connection; start a transaction
    ...                                               # statements
                                                      # normal exit => COMMIT; exception => ROLLBACK; connection returned to the pool
```

Patterns visible in the repo that are worth studying:

1. **Savepoints for nested units.** In `accounts.register`:

```python
try:
    with conn.transaction():                           # inside an open transaction this is a SAVEPOINT
        row = conn.execute("INSERT INTO users ... RETURNING id", ...).fetchone()
except psycopg.errors.UniqueViolation as exc:
    raise EmailTaken from exc
```

*"A failed insert must not poison the caller's transaction."* In Postgres, any error aborts the entire transaction ("current transaction is aborted") unless you roll back to a savepoint. The inner `transaction()` block makes the failure recoverable.

2. **Commit before raising.** In `/auth/login`, a failed password must (a) record an audit entry and (b) answer 401. Raising an exception would roll back the audit insert, so the code does `audit.append(...)`, then **`conn.commit()`**, *then* raises. Same for refresh-token reuse: the **revocation and its audit record must persist even though the response is an error**. The accounts module's docstring states the rule: *"Failure cases that must still be saved are returned as a status, never raised, so the caller commits them."*

3. **Row locks for read-modify-write.** `rotate` does `SELECT ... FROM refresh_tokens WHERE token_hash = %s FOR UPDATE`, which **locks the row until commit**. Two simultaneous refreshes with the same token serialise: the first marks it used; the second sees `used_at` set and is treated as replay. Without the lock, both might read "unused" and both succeed (a **lost update / double spend**).

4. **Advisory locks** (application-defined mutexes in the database): `pg_advisory_xact_lock(727001)` inside `audit.append` (held until the transaction ends) serialises chain appends so the chain cannot fork; `pg_advisory_lock(727002)` in `migrate` stops two containers starting together from both migrating. Advisory locks are great for "only one of these at a time" across *processes*, where an in-process Python lock would not help.

### Isolation levels and anomalies

| Anomaly | Meaning |
|---|---|
| **Dirty read** | reading another transaction's uncommitted data |
| **Non-repeatable read** | the same row read twice returns different values |
| **Phantom read** | the same query returns a different *set* of rows |
| **Lost update** | two read-modify-writes overwrite each other |
| **Write skew** | two transactions each check a condition then update different rows, jointly violating a rule |

Postgres levels: **READ COMMITTED** (default: each statement sees data committed before it began; prevents dirty reads), **REPEATABLE READ** (snapshot for the whole transaction; PG's implementation also prevents phantoms), **SERIALIZABLE** (as if run one at a time; may abort with a serialization failure you must retry). Choose the weakest level that is correct; protect specific read-modify-write spots with `FOR UPDATE`, unique constraints, or atomic SQL (`UPDATE ... SET n = n + 1`).

### MVCC

Postgres uses **multi-version concurrency control**: writers create new row versions; readers see a consistent snapshot without blocking writers, and vice versa. Old versions are cleaned by **VACUUM** (autovacuum). Consequences: updates are "delete + insert" (bloat), long-running transactions hold back cleanup, and readers never wait for writers.

### Deadlocks

Transaction A locks row 1 then wants row 2; B locks row 2 then wants row 1. Postgres detects it and aborts one. Prevent by **locking in a consistent order** and keeping transactions short. **Never hold a transaction open across a slow external call** (a model call or HTTP request): it holds locks and a connection. Look at `chat.py`: database work happens in short `with pool.connection()` blocks *before* and *after* the long streaming agent run, never across it.

## 17.5 Indexes and query performance

An **index** is a separate data structure (usually a B-tree) letting the database find rows without scanning the table. It speeds reads, slows writes (every insert/update maintains each index) and costs space.

| Index type | Use |
|---|---|
| **B-tree** (default) | equality, range, `ORDER BY`, prefix `LIKE 'abc%'` |
| **Unique** | enforce uniqueness + fast lookup |
| **Composite** `(a, b)` | queries filtering on `a`, or `a` and `b` (the leftmost-prefix rule; order matters) |
| **Expression** `lower(email)` | queries using that exact expression |
| **Partial** `WHERE disabled_at IS NULL` | index only the rows you query |
| **GIN** | `jsonb` containment, arrays, full-text (`tsvector`) |
| **GiST/SP-GiST** | geometric/range types |
| **BRIN** | huge, naturally ordered tables (timestamps) |
| **HNSW/IVFFlat** (pgvector) | vector similarity (Chapter 10) |
| **Hash** | equality only (rarely better than B-tree) |

**Design from the queries.** For each hot query, ask which columns it filters and sorts on. The repo's four non-trivial indexes each map to a named query (Section 17.2). Over-indexing slows inserts (audit writes!) and bloats memory; under-indexing makes lists slow.

### `EXPLAIN` and `EXPLAIN ANALYZE`

```sql
EXPLAIN ANALYZE
SELECT id, title, updated_at FROM conversations
WHERE user_id = '...' ORDER BY updated_at DESC LIMIT 30;
```

Read the plan bottom-up: **Index Scan / Index Only Scan** (good for selective queries), **Seq Scan** (scans the whole table: fine for tiny tables, bad for big ones), **Bitmap Heap Scan**, **Sort** (an explicit sort means no index served the order), **Hash Join / Nested Loop / Merge Join**, `rows=` estimates vs actual (big mismatch = stale statistics: run `ANALYZE`), `actual time`, `loops`, `Buffers`. On tiny tables Postgres rightly prefers a sequential scan; test index behaviour with realistic data volumes.

### Selectivity and statistics

An index helps when it narrows to few rows. An index on a column with two values (`confidence`) is rarely useful alone. Postgres keeps statistics (`pg_stats`); `ANALYZE` (autovacuum does it) refreshes them.

## 17.6 Migrations

A **migration** is a versioned, ordered change to the schema. Never edit a production schema by hand; never edit an applied migration.

### This repo's runner (`db.py`)

```python
def migrate(url=None, directory=MIGRATIONS_DIR) -> list[str]:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))      # one migrator at a time
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz DEFAULT now())")
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            for path in sorted(directory.glob("*.sql")):                    # 001_init.sql, 002_...
                if path.stem in done: continue
                with conn.transaction():                                    # all of a file, or none of it
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))
```

Properties to recognise: **numbered, forward-only plain SQL files**; a **ledger table**; **idempotent** (re-running applies nothing new); **transactional** (Postgres supports transactional DDL, so a failed migration leaves no half-applied schema); **concurrency-safe** (advisory lock); runs **at API startup** (`create_app(run_migrations=True)`), convenient for small apps. For larger systems, run migrations as a **separate release step** (a job before rolling out new code) so that many instances do not race and so you can control timing.

### Safe schema changes in production (expand/contract)

Deploys are not instantaneous: old and new code run **simultaneously** for a while, so the schema must work for both. Patterns:

1. **Expand**: add the new column/table (nullable or with default), deploy code that writes to both/new.
2. **Migrate data** (in batches).
3. **Contract**: after all code uses the new shape, drop the old one in a later release.

Dangerous operations on big tables: adding a column with a volatile default, adding an index without `CONCURRENTLY`, adding a `NOT NULL` or foreign key without validating in steps, long `ALTER TABLE` locks. Tools: **Alembic** (SQLAlchemy), **Flyway**, **Liquibase**, **sqitch**, **Prisma Migrate**, **Django migrations**; this repo's plain SQL is transparent ("read it top to bottom to see exactly what the database holds").

### Testing migrations

`tests/conftest.py` creates a **brand-new database per test** (`CREATE DATABASE stylist_test_<hex>`), runs `migrate()`, and drops it afterwards (`DROP DATABASE ... WITH (FORCE)`). Every test run therefore proves the migrations apply cleanly from scratch, against a **real Postgres** rather than a mock; tests skip if Postgres is not running. *Test SQL against the real engine*: triggers, constraints and locks cannot be mocked faithfully.

## 17.7 Connections and pools

Opening a Postgres connection costs a TCP+auth handshake and a **server process** (Postgres forks one backend per connection; typically `max_connections` ≈ 100). So applications use a **connection pool**:

```python
ConnectionPool(url, min_size=1, max_size=10, kwargs={"row_factory": dict_row, "autocommit": autocommit}, open=True)
```

* **Size** limits concurrent database work per process. With `p` processes × `max_size` connections, keep the total under the server's `max_connections`. Too many connections slow Postgres; **PgBouncer** (a connection pooler) multiplexes many app connections onto few server connections.
* **Pool exhaustion**: when all connections are checked out (a leak, or transactions held across slow calls), new requests wait and eventually time out. Symptom: everything hangs while the database looks idle.
* **Two pools here**: the transactional pool for request code, and a separate **autocommit** pool for LangGraph's `PostgresSaver` (which requires it). Remember they have different transaction semantics.
* **`row_factory=dict_row`**: rows come back as dicts, so code reads `row["id"]`.
* Close pools at shutdown (`lifespan`).

## 17.8 Postgres features worth knowing (beyond this repo)

* **Row-Level Security (RLS)**: policies that restrict which rows a database role can see, a strong multi-tenant isolation tool (this app enforces ownership in application code with `WHERE user_id = %s`; RLS would add a database-level backstop).
* **Roles and privileges**: separate roles for migrations (owner, can alter) and the application (only `SELECT/INSERT/UPDATE` as needed; no `DROP`, no `ALTER`, no trigger changes). *The audit triggers protect nothing if the app connects as the table owner and can drop them.* This repo uses a single `stylist` user (fine locally; production should split roles).
* **Full-text search** (`tsvector`, `to_tsquery`, GIN) and **trigram** matching (`pg_trgm`) for fuzzy search.
* **Extensions**: `pgvector`, `PostGIS`, `pg_stat_statements` (find slow queries), `pgcrypto`.
* **Partitioning**, **materialized views**, **LISTEN/NOTIFY** (lightweight pub/sub), **logical replication**.
* **`SELECT ... FOR UPDATE SKIP LOCKED`**: build a job queue in Postgres.

## 17.9 Backups, replication and recovery

"**No backups are configured**" is a line in this repo's deployment guide, and an honest one. A database without tested restores is a liability.

* **Logical backups**: `pg_dump` / `pg_restore` (portable, simple, restore time grows with size).
* **Physical backups and PITR**: base backup + continuous **WAL archiving** lets you restore to *any moment* (point-in-time recovery), e.g. "five minutes before the bad deploy".
* **Replication**: streaming **replicas** for read scaling and failover; **synchronous** replicas lose no committed data on failover (slower), **asynchronous** may lose a little.
* **Managed databases** (AWS RDS/Aurora, Google Cloud SQL, Azure, Neon, Supabase) automate backups, patching, failover.
* **RPO / RTO**: how much data can we lose (Recovery Point Objective) and how long can we be down (Recovery Time Objective)? Decide these, then choose mechanisms.
* **The cardinal rule**: **a backup you have never restored is not a backup.** Schedule restore drills.
* **Encrypt backups**, store them off the machine, and keep retention that matches policy (and deletion requests: backups contain deleted data until they age out).

A minimal improvement for the single-VM deployment (cron on the host):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec -T postgres \
  pg_dump -U stylist stylist | gzip > /backups/stylist-$(date +%F).sql.gz     # then copy off-box, rotate, and test restore
```

## 17.10 Other data stores and when to choose them

| Store | Strength | Typical AI-app use |
|---|---|---|
| **PostgreSQL** | relational integrity, SQL, extensions, JSONB, vectors | the default system of record (this app) |
| **Redis** | in-memory, microsecond latency, rich structures (strings, hashes, sets, sorted sets, streams), TTLs, atomic ops, pub/sub | caches, **rate limiters**, replay/jti sets, sessions, queues, locks. The natural home for this app's in-memory limiters when scaling out (Chapter 32) |
| **SQLite / libSQL** | embedded, zero ops | local tools, tests, Mastra's storage and audit chain in this repo |
| **MongoDB** (document) | flexible schemas, nested documents | content-like data, prototyping; beware weak integrity if misused |
| **DynamoDB / Cassandra** (key-value/wide-column) | massive scale, predictable latency, partitioned | very high throughput with known access patterns |
| **Elasticsearch / OpenSearch** | full-text, faceting, logs, hybrid search | search-heavy apps, log analytics |
| **Vector databases** | similarity search | RAG (Chapter 10), or pgvector |
| **Neo4j** (graph) | relationship traversals | knowledge graphs |
| **Time-series** (TimescaleDB, InfluxDB, Prometheus TSDB) | metrics/events over time | monitoring |
| **Columnar/OLAP** (BigQuery, Snowflake, ClickHouse, DuckDB) | analytics over huge data | product analytics, eval analysis |
| **Object storage** (S3, GCS, R2) | cheap blobs | documents, images (e.g. a future try-on feature), backups |

**CAP theorem** (distributed systems): under a network partition you must choose **consistency** or **availability**; many stores are tunable. **BASE** (basically available, soft state, eventually consistent) is the trade made for scale. Default to Postgres until you can name a concrete limit it hits.

## 17.11 Securing the database

* **Parameterise** all queries (Section 17.3).
* **Least-privilege roles**; separate migration and runtime roles; no superuser for the app.
* **Network**: do not publish the database port to the internet (in `docker-compose.prod.yml` Postgres has no published port; the dev compose publishes 5432 for convenience and should not be exposed on a server).
* **Strong, generated passwords** (`init_production_env.py` generates a 32-byte URL-safe `POSTGRES_PASSWORD`); never reuse dev defaults.
* **Encryption**: TLS to the database off-box; encryption at rest (disk/volume or managed-service setting).
* **Minimise sensitive data**: hash what you only need to verify (passwords, refresh tokens), store fingerprints instead of content where possible (audit log).
* **Audit and monitor** access; keep logs free of data values.
* **Backups** are copies of your data: protect them equally.
* **Injection through JSONB/identifiers/ORDER BY** is also real: validate and allow-list.
* **Mind cascades** and soft-delete policies for privacy requests.

## 17.12 Practical performance checklist

* Know your hot queries; index for them; verify with `EXPLAIN ANALYZE` on realistic data.
* Avoid `SELECT *` in hot paths; fetch only needed columns.
* Avoid N+1; batch.
* Keep transactions short; never across network calls.
* Right-size pools; watch active/idle connections.
* Use `pg_stat_statements` to find slow/frequent queries.
* Monitor table/index bloat, autovacuum, disk growth, replication lag.
* Cache read-heavy, rarely changing data (Redis or in-process TTL).
* Archive or partition high-volume append-only tables (the audit log grows forever: plan retention *without* breaking the chain, e.g. by checkpointing and exporting verified segments).

## 17.13 Practice queries on this schema

1. Conversations per user, newest first, with the number of outfit batches delivered.
2. Average total price per style, only styles with ≥ 3 outfits.
3. The three most expensive outfits for each user (window function with `rank() ... <= 3`).
4. Find users whose refresh token family has been revoked after reuse (join `refresh_tokens` and `audit_log` where `action = 'refresh_token_reuse_detected'`).
5. Count audit events per action per hour for the last day (`date_trunc('hour', ts)`).
6. Detect a broken audit chain with one `lag()` query.
7. Which retailers appear most in `outfit_items`, split by `verification->>'confidence'`? (JSONB operators `->>`.)

## Common mistakes

* Concatenating user input into SQL.
* Floats for money; `timestamp` without time zone.
* Missing indexes on foreign keys and hot filters; too many indexes on write-heavy tables.
* Holding transactions open across slow external calls.
* Raising an exception when a state change (audit, revocation) must be committed.
* Relying on application checks only; no constraints.
* Running migrations by hand in production, editing applied migrations.
* No backup/restore drills.
* The app connecting as the schema owner.
* Assuming an in-process lock protects multiple instances.

## Summary

* Model data relationally with keys and constraints; put invariants in the database; denormalise deliberately; use JSONB for evidence-like blobs.
* SQL fluency (joins, aggregates, CTEs, windows, NULL logic) plus parameterised queries.
* Transactions give ACID; know isolation levels, row locks (`FOR UPDATE`), advisory locks, savepoints, and when a failure must still be committed.
* Index from queries, verify with `EXPLAIN ANALYZE`; mind write cost.
* Migrations are numbered, transactional, idempotent and concurrency-safe; use expand/contract in production; test them on a real database.
* Pools, roles, backups and encryption are part of the design, not afterthoughts.
* Choose other stores (Redis, vector, search, OLAP, object) for specific needs.

## Key terms

*primary/foreign key, constraint, normalisation, JSONB, UUID, `timestamptz`, ACID, isolation level, MVCC, lock, advisory lock, savepoint, deadlock, index, B-tree, composite/expression/partial index, `EXPLAIN`, migration, expand/contract, connection pool, PgBouncer, WAL, PITR, replica, RPO/RTO, SQL injection, RLS.*

## Interview questions

1. What is ACID? Give an example from this app where atomicity matters.
2. Explain READ COMMITTED and a lost-update anomaly. How does `FOR UPDATE` help in refresh-token rotation?
3. Why does `login` call `conn.commit()` before raising `HTTPException`?
4. Design an index for "a user's recent conversations". Why `(user_id, updated_at DESC)`?
5. What is SQL injection and how is it prevented? Can you parameterise a table name?
6. How do you run a zero-downtime migration that renames a column?
7. What does a connection pool do? What happens when it is exhausted?
8. Why is `timestamptz` preferred? Why integer money?
9. When would you add Redis? When would you add a vector database instead of pgvector?
10. How would you back up and restore this database? What are RPO and RTO?

## Exercises

1. Start the dev Postgres, run `\d+ outfits` in `psql`, and map every column and constraint to a design decision.
2. Insert 100,000 fake conversations; compare `EXPLAIN ANALYZE` for the recent-conversations query with and without the composite index.
3. Reproduce a lost update with two `psql` sessions, then fix it with `FOR UPDATE` and with an atomic `UPDATE`.
4. Write migration `002_...sql` adding a nullable `conversations.archived_at` and a partial index on non-archived rows; add a test that migrates from scratch.
5. Write and test a nightly `pg_dump` script plus a restore into a scratch database, and verify the audit chain on the restored copy.
