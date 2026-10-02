"""The audit log: an append-only record that makes tampering detectable.

Every entry stores the hash of the entry before it:

    hash = SHA-256( previous hash + this entry's time, actor, action and details )

Change or delete any entry and its hash, and every hash after it, no longer matches, so
`verify_chain` finds the first broken link. The database also refuses UPDATE, DELETE and TRUNCATE
on the table (see 001_init.sql). A database administrator could remove those protections, but not
without the chain breaking.

Only ids, counts and short codes go into `details`. Never passwords, tokens or message text.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg

GENESIS = "0" * 64  # the "previous hash" of the very first entry
AUDIT_LOCK = 727_001  # one writer at a time, so the chain cannot fork


def _canonical(ts: str, actor: str, action: str, details: dict, prev: str) -> str:
    # fixed key order and no spaces: the same entry must always produce the same bytes
    return json.dumps(
        {"ts": ts, "actor": actor, "action": action, "details": details, "prev": prev},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )


def compute_hash(ts: str, actor: str, action: str, details: dict, prev: str) -> str:
    return hashlib.sha256(_canonical(ts, actor, action, details, prev).encode()).hexdigest()


def _ts_text(ts: datetime) -> str:
    return ts.astimezone(UTC).isoformat(timespec="microseconds")


def append(conn: psycopg.Connection, actor: str, action: str, details: dict | None = None) -> str:
    """Add one entry. Call inside the caller's transaction; returns the new entry's hash."""
    details = details or {}
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (AUDIT_LOCK,))  # held until the transaction ends
    row = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = _first_value(row) if row else GENESIS
    ts = datetime.now(UTC)  # Postgres keeps microseconds, so the stored value hashes back identically
    digest = compute_hash(_ts_text(ts), actor, action, details, prev)
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, details, prev_hash, hash) VALUES (%s, %s, %s, %s, %s, %s)",
        (ts, actor, action, json.dumps(details), prev, digest),
    )
    return digest


def _first_value(row) -> str:
    return row["hash"] if isinstance(row, dict) else row[0]


@dataclass
class ChainReport:
    ok: bool
    entries: int
    first_bad_id: int | None = None
    reason: str | None = None


def verify_chain(conn: psycopg.Connection) -> ChainReport:
    """Walk the whole log in order, recomputing every hash. Fast enough for this project's size;
    for a very large log you would verify in slices and remember a checkpoint."""
    prev, count = GENESIS, 0
    cur = conn.execute("SELECT id, ts, actor, action, details, prev_hash, hash FROM audit_log ORDER BY id")
    for r in cur:
        row = r if isinstance(r, dict) else dict(zip(("id", "ts", "actor", "action", "details", "prev_hash", "hash"), r, strict=True))
        count += 1
        if row["prev_hash"] != prev:
            return ChainReport(False, count, row["id"], "an entry before this one was removed or changed")
        expected = compute_hash(_ts_text(row["ts"]), row["actor"], row["action"], row["details"], prev)
        if row["hash"] != expected:
            return ChainReport(False, count, row["id"], "this entry's contents do not match its hash")
        prev = row["hash"]
    return ChainReport(True, count)
