"""Accounts and sessions, as plain functions over a database connection.

Each function leaves committing to the caller. Failure cases that must still be saved (revoking a
stolen token's family) are returned as a status, never raised, so the caller commits them.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

import psycopg

from api.config import Settings, settings
from api.security.passwords import (
    check_policy,
    hash_password,
    needs_rehash,
    verify_password,
)
from api.security.tokens import hash_refresh_token, new_refresh_token

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class EmailTaken(Exception):
    pass


class InvalidEmail(ValueError):
    """The message is safe to show to the user."""


class InvalidCredentials(Exception):
    """Wrong email or password, or a disabled account. Deliberately does not say which."""


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise InvalidEmail("Enter a valid email address.")
    return email


def register(conn: psycopg.Connection, email: str, password: str) -> tuple[str, str]:
    """Create an account. Returns (user id, normalised email). Raises InvalidEmail, WeakPassword
    or EmailTaken."""
    email = normalize_email(email)
    check_policy(password, email)
    try:
        with conn.transaction():  # a failed insert must not poison the caller's transaction
            row = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id",
                (email, hash_password(password)),
            ).fetchone()
    except psycopg.errors.UniqueViolation as exc:
        raise EmailTaken from exc
    return str(row["id"]), email


def authenticate(conn: psycopg.Connection, email: str, password: str) -> str:
    """Return the user id if the email and password are right. Takes the same time whether or not
    the email exists. Raises InvalidCredentials otherwise."""
    try:
        email = normalize_email(email)
    except InvalidEmail:
        verify_password(password, None)  # still spend the time
        raise InvalidCredentials from None
    row = conn.execute(
        "SELECT id, password_hash, disabled_at FROM users WHERE lower(email) = %s", (email,)
    ).fetchone()
    ok = verify_password(password, row["password_hash"] if row else None)
    if not ok or row is None or row["disabled_at"] is not None:
        raise InvalidCredentials
    if needs_rehash(row["password_hash"]):  # hashing settings were strengthened since this was stored
        conn.execute("UPDATE users SET password_hash = %s WHERE id = %s", (hash_password(password), row["id"]))
    return str(row["id"])


def start_session(conn: psycopg.Connection, user_id: str, cfg: Settings = settings) -> str:
    """A new login: a brand-new token family. Returns the refresh token for the browser's cookie."""
    return _issue_refresh(conn, user_id, uuid.uuid4(), cfg)


def _issue_refresh(conn: psycopg.Connection, user_id: str, family: uuid.UUID, cfg: Settings) -> str:
    raw, hashed = new_refresh_token()
    conn.execute(
        "INSERT INTO refresh_tokens (user_id, family_id, token_hash, expires_at) VALUES (%s, %s, %s, now() + %s)",
        (user_id, family, hashed, timedelta(seconds=cfg.auth_refresh_ttl_s)),
    )
    return raw


@dataclass
class Rotation:
    status: str  # "ok" | "invalid" | "reuse"
    user_id: str | None = None
    new_token: str | None = None


def rotate(conn: psycopg.Connection, raw_token: str, cfg: Settings = settings) -> Rotation:
    """Exchange a refresh token for a new one. The old token stops working.

    If an already-exchanged token is presented again, someone is replaying a copy: the whole family
    is revoked, so both the thief and the real owner are logged out and must log in again."""
    row = conn.execute(
        "SELECT id, user_id, family_id, used_at, revoked_at, expires_at, expires_at <= now() AS expired"
        " FROM refresh_tokens WHERE token_hash = %s FOR UPDATE",
        (hash_refresh_token(raw_token),),
    ).fetchone()
    if row is None or row["revoked_at"] is not None:
        return Rotation("invalid")
    if row["used_at"] is not None:
        conn.execute(
            "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL",
            (row["family_id"],),
        )
        return Rotation("reuse", str(row["user_id"]))
    if row["expired"]:
        return Rotation("invalid")
    disabled = conn.execute("SELECT disabled_at FROM users WHERE id = %s", (row["user_id"],)).fetchone()
    if disabled is None or disabled["disabled_at"] is not None:
        return Rotation("invalid")
    conn.execute("UPDATE refresh_tokens SET used_at = now() WHERE id = %s", (row["id"],))
    return Rotation("ok", str(row["user_id"]), _issue_refresh(conn, str(row["user_id"]), row["family_id"], cfg))


def end_session(conn: psycopg.Connection, raw_token: str) -> str | None:
    """Log out: revoke the token's whole family. Returns the user id if the token was known."""
    row = conn.execute(
        "SELECT user_id, family_id FROM refresh_tokens WHERE token_hash = %s", (hash_refresh_token(raw_token),)
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s AND revoked_at IS NULL",
        (row["family_id"],),
    )
    return str(row["user_id"])


def get_user(conn: psycopg.Connection, user_id: str) -> dict | None:
    return conn.execute(
        "SELECT id, email, created_at FROM users WHERE id = %s AND disabled_at IS NULL", (user_id,)
    ).fetchone()
