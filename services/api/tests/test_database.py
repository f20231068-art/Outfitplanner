"""The schema, its safety rules, and the hash-chained audit log, against a real Postgres."""

from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.rows import dict_row

from api.audit import GENESIS, append, compute_hash, verify_chain
from api.db import migrate


def one(conn, query, params=()):
    return conn.execute(query, params).fetchone()


def new_user(conn, email="a@example.com"):
    return one(conn, "INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id", (email,))["id"]


# ---- migrations ---------------------------------------------------------------------------------
def test_migrations_create_the_tables_and_running_again_does_nothing(db_url):
    with psycopg.connect(db_url) as conn:
        tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")}
    assert {"users", "refresh_tokens", "conversations", "outfits", "outfit_items", "audit_log", "schema_migrations"} <= tables
    assert migrate(db_url) == []  # already applied: nothing happens


# ---- constraints keep bad data out ----------------------------------------------------------------
def test_the_same_email_in_a_different_case_cannot_register_twice(pool):
    with pool.connection() as conn:
        new_user(conn, "Alice@Example.com")
        with pytest.raises(psycopg.errors.UniqueViolation):
            new_user(conn, "alice@example.com")


def test_an_email_without_an_at_sign_is_rejected(pool):
    with pool.connection() as conn, pytest.raises(psycopg.errors.CheckViolation):
        new_user(conn, "not-an-email")


def test_outfit_rules_are_enforced_by_the_database(pool):
    with pool.connection() as conn:
        uid = new_user(conn)
        cid = one(conn, "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (uid,))["id"]

        def outfit(position=1, total=2000, confidence="high"):
            return conn.execute(
                "INSERT INTO outfits (conversation_id, user_id, position, style_name, total_inr, confidence, rationale)"
                " VALUES (%s, %s, %s, 's', %s, %s, 'r')", (cid, uid, position, total, confidence))

        outfit()
        for bad, error in [
            ({"position": 1}, psycopg.errors.UniqueViolation),  # the same slot twice
            ({"position": 2, "total": 0}, psycopg.errors.CheckViolation),  # a free outfit
            ({"position": 3, "confidence": "maybe"}, psycopg.errors.CheckViolation),
        ]:
            with pytest.raises(error), conn.transaction():
                outfit(**bad)


def test_deleting_a_user_removes_their_conversations_and_outfits(pool):
    with pool.connection() as conn:
        uid = new_user(conn)
        cid = one(conn, "INSERT INTO conversations (user_id) VALUES (%s) RETURNING id", (uid,))["id"]
        conn.execute("INSERT INTO outfits (conversation_id, user_id, position, style_name, total_inr, confidence, rationale)"
                     " VALUES (%s, %s, 1, 's', 100, 'low', 'r')", (cid, uid))
        conn.execute("DELETE FROM users WHERE id = %s", (uid,))
        assert one(conn, "SELECT count(*) AS n FROM conversations")["n"] == 0
        assert one(conn, "SELECT count(*) AS n FROM outfits")["n"] == 0


# ---- the audit log ----------------------------------------------------------------------------------
def test_each_entry_is_linked_to_the_one_before_and_the_chain_verifies(pool):
    with pool.connection() as conn:
        h1 = append(conn, "user_1", "login", {"ok": True})
        h2 = append(conn, "user_1", "tool_call", {"tool": "search_products"})
        rows = conn.execute("SELECT prev_hash, hash FROM audit_log ORDER BY id").fetchall()
        assert rows[0]["prev_hash"] == GENESIS and rows[0]["hash"] == h1
        assert rows[1]["prev_hash"] == h1 and rows[1]["hash"] == h2
        report = verify_chain(conn)
    assert report.ok and report.entries == 2


def test_the_hash_is_reproducible_from_the_entry(pool):
    with pool.connection() as conn:
        append(conn, "u", "a", {"k": 1})
        row = one(conn, "SELECT * FROM audit_log")
        from api.audit import _ts_text
        assert row["hash"] == compute_hash(_ts_text(row["ts"]), "u", "a", {"k": 1}, GENESIS)


def test_the_database_refuses_to_update_delete_or_truncate_the_log(pool):
    with pool.connection() as conn:
        append(conn, "u", "a")
        for statement in ("UPDATE audit_log SET actor = 'evil'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
            with pytest.raises(psycopg.errors.RaiseException, match="append-only"), conn.transaction():
                conn.execute(statement)
        assert verify_chain(conn).ok


def _tamper(url, statement, params=()):
    """What an attacker with full database power would do: switch the protections off, edit, switch on."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("ALTER TABLE audit_log DISABLE TRIGGER USER")
        conn.execute(statement, params)
        conn.execute("ALTER TABLE audit_log ENABLE TRIGGER USER")


def _filled(url, n=5):
    with psycopg.connect(url) as conn:
        for i in range(n):
            append(conn, "user_1", "event", {"i": i})
        conn.commit()


def _verify(url):
    with psycopg.connect(url) as conn:
        return verify_chain(conn)


def test_editing_an_entry_is_detected_even_if_the_triggers_are_bypassed(db_url):
    _filled(db_url)
    _tamper(db_url, "UPDATE audit_log SET details = '{\"i\": 999}' WHERE id = (SELECT id FROM audit_log ORDER BY id OFFSET 2 LIMIT 1)")
    report = _verify(db_url)
    assert not report.ok and "contents" in report.reason


def test_deleting_an_entry_is_detected(db_url):
    _filled(db_url)
    _tamper(db_url, "DELETE FROM audit_log WHERE id = (SELECT id FROM audit_log ORDER BY id OFFSET 2 LIMIT 1)")
    report = _verify(db_url)
    assert not report.ok and "removed" in report.reason


def test_rewriting_an_entry_and_its_own_hash_still_breaks_the_next_link(db_url):
    """A cleverer attacker edits an entry AND recomputes that entry's hash. The NEXT entry still
    points at the old hash, so the chain breaks there."""
    _filled(db_url)
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as conn:
        victim = one(conn, "SELECT * FROM audit_log ORDER BY id OFFSET 1 LIMIT 1")
        from api.audit import _ts_text
        forged = compute_hash(_ts_text(victim["ts"]), "user_1", "event", {"i": 777}, victim["prev_hash"])
    _tamper(db_url, "UPDATE audit_log SET details = '{\"i\": 777}', hash = %s WHERE id = %s", (forged, victim["id"]))
    report = _verify(db_url)
    assert not report.ok and report.first_bad_id == victim["id"] + 1


def test_many_writers_at_once_still_produce_one_unbroken_chain(db_url):
    def write(i):
        with psycopg.connect(db_url) as conn:
            append(conn, f"user_{i % 4}", "event", {"i": i})
            conn.commit()

    with ThreadPoolExecutor(max_workers=12) as pool_:
        list(pool_.map(write, range(60)))
    report = _verify(db_url)
    assert report.ok and report.entries == 60  # no forks, no gaps
