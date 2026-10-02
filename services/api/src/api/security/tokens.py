"""The two credentials a logged-in browser holds.

ACCESS token: a signed JWT (RS256), valid 15 minutes, sent with every API request. Short-lived
  because it cannot be cancelled once issued: expiry is the only way it stops working.
REFRESH token: a random secret, valid 14 days, kept in an HttpOnly cookie that scripts cannot read.
  Used only to get a new access token. Only its hash is stored. Each use replaces it with a new one
  (rotation); if an already-used one shows up again it was stolen, so the whole family is revoked.
"""

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass

import jwt

from api.config import Settings, settings


class InvalidToken(Exception):
    """Bad, expired or forged access token. Never says which, so it tells an attacker nothing."""


@dataclass(frozen=True)
class Identity:
    user_id: str


def mint_access_token(user_id: str, cfg: Settings = settings, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    claims = {
        "iss": cfg.auth_jwt_issuer, "aud": cfg.auth_jwt_audience, "sub": user_id,
        "iat": issued, "exp": issued + cfg.auth_access_ttl_s, "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, cfg.auth_private_key_pem, algorithm="RS256")


def verify_access_token(token: str, cfg: Settings = settings) -> Identity:
    try:
        claims = jwt.decode(
            token, cfg.auth_public_key_pem,
            algorithms=["RS256"],  # pinned: never trust the algorithm the token asks for
            audience=cfg.auth_jwt_audience, issuer=cfg.auth_jwt_issuer, leeway=cfg.auth_jwt_leeway_s,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken from exc
    return Identity(user_id=str(claims["sub"]))


def new_refresh_token() -> tuple[str, str]:
    """(the secret to give the browser, the hash to store)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    # a fast hash is fine here: the input is 384 random bits, so it cannot be guessed or brute-forced
    return hashlib.sha256(raw.encode()).hexdigest()
