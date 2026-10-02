"""Password handling. Passwords are never stored: only an Argon2id hash, which is slow and memory-hungry
on purpose, so guessing passwords from a stolen copy of the database is very expensive."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2-cffi's defaults follow current OWASP guidance

MIN_LENGTH = 10
MAX_LENGTH = 128  # a limit stops someone sending a megabyte "password" to burn our CPU
# A tiny deny-list of passwords everyone tries first. A real deployment would check a breach list.
COMMON = {
    "password", "password1", "password12", "password123", "1234567890", "12345678910",
    "qwertyuiop", "qwerty12345", "iloveyou123", "welcome123", "letmein123", "admin12345",
}


class WeakPassword(ValueError):
    """The message is safe to show to the user."""


def check_policy(password: str, email: str) -> None:
    if len(password) < MIN_LENGTH:
        raise WeakPassword(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        raise WeakPassword(f"Use at most {MAX_LENGTH} characters.")
    if password.lower() in COMMON:
        raise WeakPassword("That password is too common. Choose a different one.")
    local = email.split("@", 1)[0].lower()
    if len(local) >= 4 and local in password.lower():
        raise WeakPassword("Your password should not contain your email name.")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


# A real hash of a throwaway password. When a login names an email that does not exist we still do
# one full verification against this, so "no such user" takes as long as "wrong password" and the
# response time cannot be used to find out which emails are registered.
_DUMMY_HASH = _hasher.hash("not-a-real-account-password")


def verify_password(password: str, stored_hash: str | None) -> bool:
    try:
        _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return stored_hash is not None  # the dummy check never counts as a success


def needs_rehash(stored_hash: str) -> bool:
    """True if the stored hash used older/weaker settings than we use now (re-hash at next login)."""
    return _hasher.check_needs_rehash(stored_hash)
