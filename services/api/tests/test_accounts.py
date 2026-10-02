"""Passwords, login tokens, throttling, and the account/session flows (against a real Postgres)."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api import accounts
from api.config import Settings
from api.security.passwords import WeakPassword, check_policy, hash_password, verify_password
from api.security.throttle import FailureCounter, SlidingWindow, TooManyAttempts
from api.security.tokens import (
    InvalidToken,
    hash_refresh_token,
    mint_access_token,
    new_refresh_token,
    verify_access_token,
)


def _pem_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode(),
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode(),
    )


AUTH_PRIV, AUTH_PUB = _pem_pair()
OTHER_PRIV, _ = _pem_pair()
CFG = Settings(auth_jwt_private_key=AUTH_PRIV, auth_jwt_public_key=AUTH_PUB, _env_file=None)
GOOD_PW = "correct horse battery"


# ---- passwords ------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "password,email",
    [("short", "a@x.com"), ("x" * 129, "a@x.com"), ("password123", "a@x.com"), ("sreehari-is-here1", "sreehari@x.com")],
)
def test_weak_passwords_are_refused_with_a_message_for_the_user(password, email):
    with pytest.raises(WeakPassword):
        check_policy(password, email)


def test_a_good_password_passes_the_policy():
    check_policy(GOOD_PW, "a@x.com")


def test_a_password_is_stored_only_as_a_hash_and_verifies():
    h = hash_password(GOOD_PW)
    assert GOOD_PW not in h and h.startswith("$argon2id$")
    assert verify_password(GOOD_PW, h) and not verify_password("wrong password", h)


def test_two_hashes_of_the_same_password_differ_because_of_the_salt():
    assert hash_password(GOOD_PW) != hash_password(GOOD_PW)


def test_a_missing_account_is_never_a_success_and_costs_about_the_same_time():
    h = hash_password(GOOD_PW)

    def timed(stored):
        start = time.perf_counter()
        ok = verify_password(GOOD_PW, stored)
        return ok, time.perf_counter() - start

    wrong_pw = timed(hash_password("another password"))[1]
    ok, no_user = timed(None)  # the right password, but no such account
    assert ok is False and h
    assert no_user > wrong_pw * 0.3  # the work is still done, so response time does not reveal the account


# ---- access tokens ----------------------------------------------------------------------------------
def test_an_access_token_round_trips_and_carries_the_user():
    assert verify_access_token(mint_access_token("user-1", CFG), CFG).user_id == "user-1"


def test_access_tokens_live_fifteen_minutes():
    claims = jwt.decode(mint_access_token("u", CFG), AUTH_PUB, algorithms=["RS256"], audience="stylist-web", issuer="stylist-api")
    assert claims["exp"] - claims["iat"] == 900


@pytest.mark.parametrize(
    "label,token",
    [
        ("expired", mint_access_token("u", CFG, now=time.time() - 3600)),
        ("signed with another key", jwt.encode({"sub": "u", "iss": "stylist-api", "aud": "stylist-web", "iat": int(time.time()), "exp": int(time.time()) + 60}, OTHER_PRIV, algorithm="RS256")),
        ("wrong audience (e.g. a service token)", jwt.encode({"sub": "u", "iss": "stylist-api", "aud": "stylist-mcp", "iat": int(time.time()), "exp": int(time.time()) + 60}, AUTH_PRIV, algorithm="RS256")),
        ("no signature", jwt.encode({"sub": "u", "iss": "stylist-api", "aud": "stylist-web", "iat": int(time.time()), "exp": int(time.time()) + 60}, None, algorithm="none")),
        ("garbage", "not.a.token"),
        ("empty", ""),
    ],
)
def test_bad_access_tokens_are_refused(label, token):
    with pytest.raises(InvalidToken):
        verify_access_token(token, CFG)


def test_a_service_token_for_the_mcp_server_cannot_be_used_to_log_in():
    from api.mcp_auth import mint_service_token

    token = mint_service_token("u", private_key_pem=AUTH_PRIV, issuer="stylist-api", audience="stylist-mcp")
    with pytest.raises(InvalidToken):
        verify_access_token(token, CFG)  # right key and issuer, but aimed at a different service


def test_refresh_tokens_are_random_unique_and_only_their_hash_is_kept():
    a, hash_a = new_refresh_token()
    b, _ = new_refresh_token()
    assert a != b and len(a) >= 60
    assert hash_a == hash_refresh_token(a) and a not in hash_a


# ---- throttling ---------------------------------------------------------------------------------------
def test_sliding_window_allows_the_limit_then_refuses_then_recovers():
    now = [0.0]
    window = SlidingWindow(2, 60, clock=lambda: now[0])
    window.check("k")
    window.check("k")
    with pytest.raises(TooManyAttempts) as exc:
        window.check("k")
    assert 1 <= exc.value.retry_after_s <= 61
    now[0] = 61
    window.check("k")


def test_five_wrong_passwords_lock_that_email_and_address_but_not_others():
    fails = FailureCounter(5, 900)
    for _ in range(5):
        fails.ensure_allowed("a@x.com|1.1.1.1")
        fails.record_failure("a@x.com|1.1.1.1")
    with pytest.raises(TooManyAttempts):
        fails.ensure_allowed("a@x.com|1.1.1.1")
    fails.ensure_allowed("a@x.com|2.2.2.2")  # same email, different address: not locked
    fails.ensure_allowed("b@x.com|1.1.1.1")  # a different email: not locked


def test_a_successful_login_clears_the_failure_count():
    fails = FailureCounter(2, 900)
    fails.record_failure("k")
    fails.clear("k")
    fails.record_failure("k")
    fails.ensure_allowed("k")


# ---- accounts and sessions against the real database ----------------------------------------------------
def test_register_then_authenticate(pool):
    with pool.connection() as conn:
        user_id, email = accounts.register(conn, "  Alice@Example.COM ", GOOD_PW)
        assert email == "alice@example.com"  # tidied and lower-cased
        assert accounts.authenticate(conn, "ALICE@example.com", GOOD_PW) == user_id
        stored = conn.execute("SELECT password_hash FROM users").fetchone()["password_hash"]
        assert GOOD_PW not in stored


def test_registering_the_same_email_twice_is_refused_and_the_connection_stays_usable(pool):
    with pool.connection() as conn:
        accounts.register(conn, "a@example.com", GOOD_PW)
        with pytest.raises(accounts.EmailTaken):
            accounts.register(conn, "A@EXAMPLE.com", GOOD_PW)
        accounts.register(conn, "b@example.com", GOOD_PW)  # the failure did not poison the transaction


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a@b", "x" * 250 + "@example.com", "two words@x.com"])
def test_invalid_emails_are_refused(pool, bad):
    with pool.connection() as conn, pytest.raises(accounts.InvalidEmail):
        accounts.register(conn, bad, GOOD_PW)


def test_wrong_password_unknown_email_and_disabled_account_all_fail_the_same_way(pool):
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        for email, pw in [("a@example.com", "wrong password!"), ("nobody@example.com", GOOD_PW), ("not an email", GOOD_PW)]:
            with pytest.raises(accounts.InvalidCredentials):
                accounts.authenticate(conn, email, pw)
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (uid,))
        with pytest.raises(accounts.InvalidCredentials):
            accounts.authenticate(conn, "a@example.com", GOOD_PW)


def test_the_refresh_token_is_stored_only_as_a_hash(pool):
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        raw = accounts.start_session(conn, uid, CFG)
        stored = conn.execute("SELECT token_hash FROM refresh_tokens").fetchone()["token_hash"]
        assert raw not in stored and stored == hash_refresh_token(raw)


def test_a_refresh_token_can_be_exchanged_once_for_a_new_one(pool):
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        first = accounts.start_session(conn, uid, CFG)
        step = accounts.rotate(conn, first, CFG)
        assert step.status == "ok" and step.user_id == uid and step.new_token not in (None, first)
        assert accounts.rotate(conn, step.new_token, CFG).status == "ok"  # the new one works too


def test_replaying_an_already_used_refresh_token_revokes_the_whole_family(pool):
    """The theft case: a copy of the old token turns up after the real owner already moved on."""
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        first = accounts.start_session(conn, uid, CFG)
        second = accounts.rotate(conn, first, CFG).new_token  # the real owner refreshes
        replay = accounts.rotate(conn, first, CFG)  # a thief presents the old token
        assert replay.status == "reuse" and replay.user_id == uid
        assert accounts.rotate(conn, second, CFG).status == "invalid"  # the owner is logged out too


def test_other_logins_of_the_same_user_are_not_affected_by_one_families_revocation(pool):
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        phone, laptop = accounts.start_session(conn, uid, CFG), accounts.start_session(conn, uid, CFG)
        accounts.rotate(conn, phone, CFG)
        assert accounts.rotate(conn, phone, CFG).status == "reuse"  # phone's family revoked
        assert accounts.rotate(conn, laptop, CFG).status == "ok"  # laptop's family untouched


def test_unknown_expired_and_disabled_refresh_tokens_are_invalid(pool):
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        assert accounts.rotate(conn, "not-a-real-token", CFG).status == "invalid"
        expired = accounts.start_session(conn, uid, CFG)
        conn.execute("UPDATE refresh_tokens SET expires_at = now() - interval '1 second'")
        assert accounts.rotate(conn, expired, CFG).status == "invalid"
        fresh = accounts.start_session(conn, uid, CFG)
        conn.execute("UPDATE users SET disabled_at = now() WHERE id = %s", (uid,))
        assert accounts.rotate(conn, fresh, CFG).status == "invalid"


def test_logging_out_revokes_the_session(pool):
    with pool.connection() as conn:
        uid, _ = accounts.register(conn, "a@example.com", GOOD_PW)
        token = accounts.start_session(conn, uid, CFG)
        assert accounts.end_session(conn, token) == uid
        assert accounts.rotate(conn, token, CFG).status == "invalid"
        assert accounts.end_session(conn, "never-issued") is None
