# Chapter 22. Integrity, Audit and Tamper Evidence

> **Learning objectives.** Explain what an audit log is for and what it must guarantee; build and verify a hash chain; understand exactly what a hash chain does and does *not* prove; use Merkle trees, signatures, anchoring and WORM storage to strengthen it; design audit records that respect privacy; and read both audit implementations in this repo (Postgres/Python and libSQL/TypeScript) closely.
>
> **Prerequisites.** Chapters 3 (hash chains, linked lists), 17 (triggers, locks), 20 (hashes).

---

## 22.1 Why an audit log

Different records answer different questions:

| Record | Question | Typical property |
|---|---|---|
| **Application log** | what is the program doing (debugging)? | free-form, rotated, may be dropped |
| **Metrics** | how is the system doing in aggregate? | numbers, no detail |
| **Trace** | what happened in this request? | per request, sampled |
| **Audit log** | **who did what, when, with what outcome, and can we trust this record?** | structured, complete, **append-only, tamper-evident**, long-retained |

An audit log supports **accountability** (who performed an admin action), **security investigation** (what did the attacker touch?), **compliance** (SOC 2, ISO 27001, regulatory evidence), **dispute resolution** ("I never clicked Buy"), and **trust in AI systems** ("what did the agent do on behalf of this user?"). For AI agents especially, an auditable trail of *which tool was called with which arguments, on whose behalf, and with what result* is becoming a baseline expectation.

### Requirements

1. **Completeness**: every security-relevant event is recorded (including *failures*).
2. **Attribution**: *who* (user id, service, or `system`/`anonymous`).
3. **Integrity**: tampering is **prevented or detectable**.
4. **Ordering**: a trustworthy sequence.
5. **Confidentiality / privacy**: do not store secrets or unnecessary personal data.
6. **Availability and retention**: kept for the required period; queryable.
7. **Separation**: written by the system, not editable by those being audited.

## 22.2 The hash chain

Idea: each record includes a cryptographic hash of the **previous record**, so records form a chain.

```
entry_n.hash = SHA-256( canonical( ts, actor, action, details, entry_{n-1}.hash ) )
```

The first entry uses a fixed **genesis** value (`"0" * 64`) as its previous hash.

```
 GENESIS ──► [#1 prev=000... hash=H1] ──► [#2 prev=H1 hash=H2] ──► [#3 prev=H2 hash=H3] ...
```

### Why it detects tampering

Suppose someone edits entry #2's `details`. Then `SHA-256(canonical(#2))` no longer equals the stored `H2`. If they also recompute `H2`, entry #3's stored `prev` (the old H2) no longer matches, and so on: they would have to **recompute every later hash**. Deleting or inserting an entry breaks the `prev` link of its successor. `verify_chain` walks the log in order, recomputing; the first mismatch is reported (`first_bad_id`, `reason`).

### What it does **not** prove (say this out loud in interviews)

A hash chain gives **tamper-evidence, not tamper-proofness**, and only relative to what an attacker can also rewrite:

1. **Wholesale rewrite.** Someone with full write access to the storage can **recompute the whole chain consistently** after editing history. Nothing inside the database can prevent that, because the hash function is public and there is no secret.
2. **Tail truncation.** Deleting the **last** N entries leaves a *valid* shorter chain; nothing inside it reveals the missing tail.
3. **Pre-chain events.** Events never recorded are invisible.
4. **Content truth.** It proves *the record was not changed since it was written*, not that the recorded facts were true or complete.
5. **Time.** `ts` is whatever the writer's clock said.

The standard cure for 1 and 2 is **anchoring**: periodically copy the **latest hash** (the *head*) to a place the log's administrator **cannot** edit. Then any rewrite or truncation produces a different head from the one you published. Anchoring options (strongest to simplest):

* **External transparency log or timestamping authority** (RFC 3161 timestamps; public logs like Sigstore Rekor, Certificate Transparency style).
* **A public blockchain timestamp** (OpenTimestamps) of the head hash.
* **WORM/immutable storage** (AWS S3 Object Lock in compliance mode, Azure immutable blobs, GCS retention locks): write the head (or whole segments) periodically.
* **A different team's system** (email the head hash to an auditor daily; commit it to a separate repository; sign it with a key held by someone else).
* **Witnesses**: several independent parties cosign the head.

The project's docs state this limit plainly: *"Tamper evidence is only as strong as a copy of the latest hash kept somewhere else. Before relying on this for anything serious, periodically write the newest hash to a place the database admin cannot edit."* It lists **external anchoring of audit hashes** under "not done". An exercise below builds it.

### Canonical serialisation: the subtle part

To hash a structure, the **exact bytes** must be reproducible. JSON has many equivalent spellings (`{"a":1,"b":2}` vs `{"b": 2, "a": 1}`), so you must define a **canonical form** and use it for both writing and verifying:

```python
def _canonical(ts, actor, action, details, prev):
    return json.dumps({"ts": ts, "actor": actor, "action": action, "details": details, "prev": prev},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True)
```

* `sort_keys=True`: stable key order. `separators=(",", ":")`: no spaces. `ensure_ascii=True`: non-ASCII escaped to `\uXXXX`, so the bytes do not depend on encoding choices.
* Include **every field you want protected** (`ts`, `actor`, `action`, `details`, `prev`).
* **Timestamps need a fixed textual form.** `_ts_text` uses UTC ISO-8601 with microseconds (`isoformat(timespec="microseconds")`). Postgres `timestamptz` stores microseconds, so *"the stored value hashes back identically"*: if the database rounded to milliseconds, verification would fail on every row. Always check that every value survives a **write → read round trip**. The same applies to JSONB: Postgres normalises key order and number formatting inside `jsonb`; hashing the *Python dict* (canonicalised on both sides) rather than the raw text avoids the difference, and the tests prove the round trip.
* **Cross-language canonicalisation**: the TypeScript implementation (`canonicalize` in `chain.ts`) re-implements sorted-key JSON by hand because `JSON.stringify` does not sort keys, and it drops `undefined` values. A second implementation must match the first byte for byte (or the two systems must verify only their *own* chain, as here, where each chain has its own table and its own code).

## 22.3 The two chains in this repository

The project has **two independent hash-chained, append-only records, deliberately separate**:

| | **`audit_log`** (Python API, Postgres) | **`audit_chain`** (Mastra app, libSQL/SQLite) |
|---|---|---|
| Records | accounts, logins/failures, token refresh and **reuse detection**, logout, conversation created, message sent (length only), outfits delivered, chat errors, buy links opened | every finished **workflow run, step, agent run, tool call, model generation, scorer run** span, plus every **eval score** |
| Actor | user id, `anonymous`, `system` | entity name or scorer id |
| Content policy | ids, counts, short codes; **never passwords, tokens or message text** | ids, names, outcome, duration, **SHA-256 fingerprints** of inputs/outputs, never the inputs/outputs themselves; error *kind* only |
| Written by | `audit.append(conn, actor, action, details)` inside the request's transaction | `AuditExporter` plugged into Mastra's tracing |
| Serialisation of appends | `pg_advisory_xact_lock(727001)` | promise chain (`this.tail.then(...)`) |
| Protection against edits | triggers refusing `UPDATE/DELETE/TRUNCATE` | triggers refusing `UPDATE` and `DELETE` (`RAISE(ABORT, ...)`) |
| Verify | `GET /admin/audit/verify` (admin only) | `npm run audit:verify` (exit code 1 on tampering) |

### Python: `audit.py`

```python
def append(conn, actor, action, details=None) -> str:
    details = details or {}
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK,))       # one writer at a time: the chain cannot fork
    row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = _first_value(row) if row else GENESIS
    ts = datetime.now(UTC)
    digest = compute_hash(_ts_text(ts), actor, action, details, prev)
    conn.execute("INSERT INTO audit_log (ts, actor, action, details, prev_hash, hash) VALUES (%s,%s,%s,%s,%s,%s)",
                 (ts, actor, action, json.dumps(details), prev, digest))
    return digest
```

Concepts at work:

* **The lock is essential.** Without it, two concurrent requests could both read the same "last hash" and each insert an entry pointing to the same parent: a **fork**, which `verify_chain` would flag as corruption. `pg_advisory_xact_lock` is released automatically at **commit or rollback**, so no manual unlock is needed (and no leaks).
* **It runs inside the caller's transaction.** If the business action rolls back, so does its audit entry: *events are recorded atomically with the changes they describe*. But for events that must persist **even when the request fails** (a failed login; refresh-token reuse), the route calls **`conn.commit()` explicitly before raising** (Chapter 17).
* **Fail closed:** if the audit insert fails (for example the database is read-only), the request transaction fails. Security-critical systems often *prefer* "no audit, no action". (The TypeScript exporter takes the opposite stance for observability data: it catches and logs failures so tracing never breaks the traced request. Know which philosophy fits which log.)
* **A global lock serialises every audit write in the system**: at modest scale this is fine (each critical section is milliseconds), but it is a **throughput ceiling** and a **contention point**. High-volume systems shard chains (per tenant or per day), batch writes through a single background writer, or use a purpose-built append-only store.

```python
def verify_chain(conn) -> ChainReport:
    prev, count = GENESIS, 0
    for r in conn.execute("SELECT id, ts, actor, action, details, prev_hash, hash FROM audit_log ORDER BY id"):
        count += 1
        if r["prev_hash"] != prev:        return ChainReport(False, count, r["id"], "an entry before this one was removed or changed")
        if r["hash"] != compute_hash(_ts_text(r["ts"]), r["actor"], r["action"], r["details"], prev):
                                          return ChainReport(False, count, r["id"], "this entry's contents do not match its hash")
        prev = r["hash"]
    return ChainReport(True, count)
```

Linear time; the docstring notes that for a very large log you would verify **in slices and remember a checkpoint** (the last verified `(id, hash)`).

The SQL triggers (`001_init.sql`) add **prevention** in front of **detection**:

```sql
CREATE TRIGGER audit_log_no_update_delete BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_log_is_append_only();
CREATE TRIGGER audit_log_no_truncate     BEFORE TRUNCATE        ON audit_log FOR EACH STATEMENT EXECUTE FUNCTION audit_log_is_append_only();
```

A table owner or superuser *can* `DROP TRIGGER`/`ALTER TABLE ... DISABLE TRIGGER`, edit rows, re-enable: the triggers stop mistakes, application bugs and ordinary SQL injection; the **chain** is what makes a privileged edit visible. This is the **two-layer** pattern: *prevent what you can; detect the rest.*

### Demonstrating tamper detection by hand

```sql
-- as the table owner (psql):
ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete;
UPDATE audit_log SET details = '{"count": 99}' WHERE id = 5;
ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete;
-- then:  GET /admin/audit/verify  ->  {"ok": false, "entries": 5, "first_bad_id": 5, "reason": "this entry's contents do not match its hash"}
```

And a pure-SQL spot check for broken links:

```sql
SELECT id FROM (
  SELECT id, prev_hash, lag(hash) OVER (ORDER BY id) AS expected FROM audit_log
) t WHERE expected IS NOT NULL AND prev_hash <> expected;
```

(This checks links only; recomputing hashes needs the canonical JSON in application code.)

### TypeScript: `chain.ts`

Same design, different stack: `canonicalize` (recursive sorted JSON), `entryHash`, an `AuditLog` class with an `init()` that creates the table and **triggers** (`BEFORE UPDATE`/`BEFORE DELETE` → `RAISE(ABORT, 'audit_chain is append-only')`), and serialised appends:

```ts
append(entry) {
  const run = this.tail.then(() => this.appendNow(entry))
  this.tail = run.catch(() => undefined)     // a failed append must not block the ones after it
  return run
}
```

A **promise chain** is an in-process queue: each append waits for the previous one, so the "read last hash, then insert" pair is atomic *within this process*. If two processes wrote to the same SQLite file, you would need a database-level mechanism; here one process (the eval run or Studio) writes at a time. Note the same *structural* lock as the Python advisory lock but at a different layer.

`AuditExporter` (a Mastra `BaseExporter`) listens to tracing events and appends entries **for finished spans of audited types** (`WORKFLOW_RUN`, `WORKFLOW_STEP`, `AGENT_RUN`, `TOOL_CALL`, `MCP_TOOL_CALL`, `MODEL_GENERATION`, `SCORER_RUN`) and for **score events**. Details recorded: trace/span ids, parent, root flag, outcome (`ok`/`error`), error *id* (not message, since messages can quote user input), duration, and **fingerprints** of input and output (`sha256(canonicalize(value)).slice(0, 32)`).

**Fingerprints** let you later prove *"this exact input was processed in this run"* (recompute the hash of a suspected input and compare) **without storing the input**, a privacy-preserving evidence pattern. The caveat: for **low-entropy** inputs (an email, a short budget phrase) an unsalted hash can be **reversed by guessing candidates**. The Python audit's `email_tag` (first 12 hex characters of an unsalted SHA-256 of the email) has the same weakness against an attacker who has the log and a list of candidate emails. A stronger design uses **HMAC with a secret key** (a "pepper") so tags cannot be recomputed without it.

## 22.4 Merkle trees

A **Merkle tree** hashes pairs of hashes up to a single **root**:

```
              root = H(H12 || H34)
             /                     \
      H12 = H(H1||H2)        H34 = H(H3||H4)
      /        \              /        \
   H1=H(e1)  H2=H(e2)     H3=H(e3)  H4=H(e4)
```

Properties that a plain chain lacks:

* A **single root** commits to *all* entries.
* An **inclusion proof** that entry e3 is in the tree needs only the **sibling hashes along its path** (here H4 and H12): **O(log n)** hashes instead of re-reading the whole log.
* **Consistency proofs** show that a later tree extends an earlier one (nothing rewritten): the basis of **Certificate Transparency** logs, which publish signed roots so anyone can audit.
* Git commits and trees are a **Merkle DAG**; blockchains use Merkle trees per block.

```python
import hashlib
H = lambda b: hashlib.sha256(b).digest()

def merkle_root(leaves: list[bytes]) -> bytes:
    level = [H(b"\x00" + x) for x in leaves]                # domain-separate leaves from inner nodes
    while len(level) > 1:
        if len(level) % 2: level.append(level[-1])           # duplicate the last node if odd (one simple convention)
        level = [H(b"\x01" + level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]
```

(The `\x00` / `\x01` prefixes are **domain separation**, preventing a second-preimage attack where an inner node is passed off as a leaf: a real detail from RFC 6962.)

**When to prefer which**: a **hash chain** is simplest for *sequential, append-only* logs where you verify everything in order. A **Merkle tree** is better for *large logs* needing **efficient proofs** and publishable roots. You can combine them (a chain of Merkle roots per batch).

## 22.5 Signatures, HMACs and immutable storage

* **Sign checkpoints** (the head hash plus a counter and time) with a private key held **outside** the database (KMS/HSM or a separate signing service). Verifiers hold only the public key. A database owner cannot forge a signed checkpoint.
* **HMAC chains** (key held by the logger) give integrity without public verifiability; **forward-secure logging** schemes evolve the key after each entry so a *later* compromise cannot forge *earlier* entries.
* **WORM storage** (Write Once Read Many): S3 **Object Lock** (compliance mode), Azure immutable storage, GCS bucket locks, append-only filesystems. The cloud provider enforces immutability even against account admins (within retention rules).
* **Separate trust domains**: ship audit events in real time to a **separate account/system** (a SIEM, a dedicated log account) with write-only access from the application.
* **Database-native options**: PostgreSQL extensions and managed ledger databases (Amazon QLDB was retired; options include immudb, Azure SQL Ledger, or a plain append-only table plus anchoring).

## 22.6 What to put in an audit record (and what not)

**Include**: timestamp (UTC), **actor** (user/service id), **action** (a stable vocabulary: `login`, `login_failed`, `buy_link_opened`), **target** (object ids), **outcome**, **request/trace id** (to correlate with logs: the API writes `request_id` and `trace_id` into `message_sent` and `outfits_delivered`), **source** (IP or client, if policy allows), and *minimal* details (counts, lengths, short codes).

**Exclude**: passwords, tokens, API keys, full message text, full personal data, anything you would be embarrassed to see in a breach. In this repo: `message_sent` stores `length`, `resuming`; `login_failed` stores only an `email_tag`; `buy_link_opened` stores the product id, store name and link verdict.

**Use a stable action vocabulary** and version it; changing names silently breaks investigations and alerts.

**Privacy vs immutability**: you cannot delete from an immutable log, so keep personal data out of it (pseudonymous ids, tags) and document that the log holds no content (Chapter 21).

## 22.7 Operating an audit log

* **Verification schedule**: run `verify_chain` regularly (a cron/CI/monitor), alert on failure, record each verification result (and anchor the head at the same time).
* **Incremental verification**: persist the last verified `(id, hash)` and verify only newer rows.
* **Growth and retention**: the table only grows. Plan **partitioning** and **archival**: export a verified segment (with its start prev-hash and end hash) to cold storage; keep the **boundary hash** so the chain can still be validated across the archive.
* **Backups and restores**: restoring an old backup **forks history** (new entries chain from an older head). Record restores as audit events and re-anchor.
* **Access control**: who can read it (it reveals behaviour), who can verify it, **nobody** can write except the application role; use a **dedicated database role** with `INSERT` and `SELECT` only on `audit_log` (this repo uses one owner-level role: Chapter 21's risk register).
* **Time**: keep clocks synchronised (NTP); consider a trusted timestamp for critical records.
* **Failure policy**: decide whether failing to audit blocks the action (security-critical: yes) or not (observability: no), and document it.
* **Performance**: serialised appends bound write throughput; measure (`audit.append` p95), keep transactions short, shard if necessary.
* **Monitor the monitor**: alert when audit writes fail or stall.

## 22.8 Related ideas

* **Event sourcing**: store *every state change as an immutable event* and derive current state by replay; the event log is the **source of truth** and a natural audit trail. Powerful but a different architecture.
* **Change data capture (CDC)**: stream database changes (Debezium, logical replication) to an external system for auditing.
* **Checksums and signatures for artefacts**: SHA-256 of release files, **cosign**-signed container images, **SLSA provenance**, so you can verify what you deployed.
* **Reproducible builds**, **immutable infrastructure** and **GitOps** (the repo is the audit trail for configuration).
* **Blockchain**: a distributed, consensus-driven hash chain; overkill for most audit needs but useful when mutually distrusting parties need a shared log.

## 22.9 Build it yourself: a hash-chained log in 40 lines

```python
import hashlib, json, time

GENESIS = "0" * 64

def h(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

class Log:
    def __init__(self): self.rows = []
    def append(self, actor: str, action: str, details: dict | None = None):
        prev = self.rows[-1]["hash"] if self.rows else GENESIS
        body = {"ts": time.time(), "actor": actor, "action": action, "details": details or {}, "prev": prev}
        self.rows.append({**body, "hash": h(body)})
    def verify(self):
        prev = GENESIS
        for i, r in enumerate(self.rows):
            body = {k: r[k] for k in ("ts", "actor", "action", "details", "prev")}
            if r["prev"] != prev or r["hash"] != h(body):
                return False, i
            prev = r["hash"]
        return True, len(self.rows)

log = Log()
for a in ("login", "message_sent", "buy_link_opened"): log.append("u1", a)
print(log.verify())                      # (True, 3)
log.rows[1]["details"] = {"x": 1}        # tamper with an entry in the middle
print(log.verify())                      # (False, 1)
log.rows.pop()                           # delete the LAST entry
print(Log.verify(log))                   # still (True, ...)  <- tail truncation is NOT detected without an anchor
```

Run it, then add an `anchor()` that stores `rows[-1]["hash"]` somewhere else and make `verify(anchor)` compare the head and entry count.

## Common mistakes

* Claiming "tamper-proof" instead of "tamper-evident".
* No external anchor.
* Hashing non-canonical JSON (verification fails randomly).
* Timestamp precision that does not survive storage.
* Letting the application role own and alter the audit table.
* Logging secrets or personal content into an immutable store.
* No fork protection (concurrent appends).
* Never verifying.
* Unsalted hashes of guessable values used as "anonymous" tags.

## Summary

* An audit log answers who/what/when and must be trustworthy: complete, attributable, ordered, privacy-preserving and tamper-evident.
* A hash chain links each record to its predecessor's hash; edits and mid-log deletions break verification; **truncation and wholesale rewrites require external anchoring** to detect.
* Canonical serialisation, round-trip-stable timestamps and a lock against forks are essential details.
* Prevention (triggers, privileges, WORM) plus detection (chain, anchored head) is the robust combination.
* Merkle trees give O(log n) inclusion proofs; signatures and KMS-held keys let checkpoints be trusted.
* The repo keeps two separate chains with privacy-preserving contents and clear, documented limits.

## Key terms

*audit log, tamper-evident vs tamper-proof, hash chain, genesis, canonical form, fork, advisory lock, anchoring, head hash, Merkle tree, inclusion proof, consistency proof, WORM, HMAC chain, fingerprint, pepper, event sourcing, CDC, retention.*

## Interview questions

1. How does a hash-chained audit log detect tampering? What attacks does it *not* detect?
2. Why is canonical serialisation necessary? Give an example of a bug if it is missing.
3. How would you anchor the chain externally, and how often?
4. Why does `audit.append` take an advisory lock, and what limits does that impose?
5. Why does the login route commit before raising an HTTP error?
6. How would you design retention for an append-only log?
7. When would you use a Merkle tree instead of a hash chain?
8. How do you reconcile an immutable audit log with a right-to-erasure request?

## Exercises

1. Implement the 40-line log, then add anchoring and a verifier that compares against the anchor; demonstrate that tail truncation is now detected.
2. Write a nightly job that calls the verification logic, stores the head hash in a separate file/bucket, and alerts if verification fails or the head moves *backwards*.
3. Change the email tag to `HMAC(secret, email)[:12]` and write a test showing the tag cannot be recomputed without the secret.
4. Implement a Merkle tree with inclusion proofs and verify a proof for one audit entry.
5. Give the application a restricted database role (`INSERT, SELECT` on `audit_log`; no DDL) and prove, with a test, that it cannot drop the triggers.
6. Write the incremental verifier that resumes from the last verified `(id, hash)` stored in a small table.
