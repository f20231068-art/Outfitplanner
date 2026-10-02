"""Who may call this server: only our API, proven by a short-lived signed token (JWT, RS256).

The API signs a token with its PRIVATE key for every request; this server verifies it with the
matching PUBLIC key. This server can check tokens but can never create one.

Two weaknesses of short-lived tokens, and how this file handles them:

1. CLOCKS DISAGREE. The API and this server never agree on the exact second. A token stamped
   "issued 8 seconds from now" would be refused as not yet valid. We allow a small, fixed leeway
   (default 10 s) and no more, because leeway also lengthens a token's life. When a token is
   refused over timing, we log how many seconds off it was, so clock trouble is visible.

2. A STOLEN TOKEN STAYS USABLE UNTIL IT EXPIRES. So each token is single-use: its unique id
   (jti) is remembered and a second use is refused. A copy captured from a log or a network
   trace cannot be replayed after the real request has used it. Combined with a token being
   minted fresh for every request (see api/mcp_auth.py) and a short lifetime, the window in
   which a stolen token is worth anything is very small.
   Limit: the memory of used ids lives inside this process. Run several copies of this server
   and each has its own memory, so a token could be replayed once against each copy. Before
   scaling out, move the used-id memory to a shared store such as Redis.
"""

import logging
import time

import jwt
from cryptography.hazmat.primitives import serialization
from fastmcp.server.auth import AccessToken, TokenVerifier

from mcp_server.config import Settings
from mcp_server.metrics import AUTH_REFUSALS

log = logging.getLogger("mcp_server.auth")

MAX_REMEMBERED = 100_000  # used token ids kept at once; if full we refuse rather than grow forever
REQUIRED_CLAIMS = ["exp", "iat", "jti", "sub", "iss", "aud"]
TIMING_ERRORS = (jwt.ExpiredSignatureError, jwt.ImmatureSignatureError, jwt.InvalidIssuedAtError)


class ReplayGuard:
    """Remembers token ids until they could no longer be valid, and refuses a second use."""

    def __init__(self, max_items: int = MAX_REMEMBERED, clock=time.time):
        self._seen: dict[str, float] = {}  # jti -> time after which we may forget it
        self._max, self._clock = max_items, clock

    def first_use(self, jti: str, forget_after: float) -> bool:
        now = self._clock()
        if len(self._seen) >= self._max:
            self._seen = {k: v for k, v in self._seen.items() if v > now}  # drop expired entries
            if len(self._seen) >= self._max:
                return False  # still full: fail closed
        if jti in self._seen and self._seen[jti] > now:
            return False
        self._seen[jti] = forget_after
        return True


def _seconds_off(token: str) -> str:
    """For logs only: how far the token's timestamps are from our clock. Never used for a decision."""
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
        now = time.time()
        return f"iat {int(claims.get('iat', now) - now):+d}s, exp {int(claims.get('exp', now) - now):+d}s vs our clock"
    except jwt.PyJWTError:
        return "unreadable"


class ServiceJWTVerifier(TokenVerifier):
    def __init__(self, public_key_pem: str, issuer: str, audience: str, leeway_s: int = 10,
                 max_lifetime_s: int = 60, replay: ReplayGuard | None = None):
        super().__init__()
        try:
            self._key = serialization.load_pem_public_key(public_key_pem.encode())
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "MCP_JWT_PUBLIC_KEY is missing or not a valid public key. Generate the key pair with "
                "`uv run --project services/mcp python scripts/generate_jwt_keys.py`. "
                "The server refuses to start without it."
            ) from exc
        self._issuer, self._audience = issuer, audience
        self._leeway, self._max_lifetime = leeway_s, max_lifetime_s
        self._replay = replay or ReplayGuard()

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["RS256"],  # pinned: never trust the algorithm the token asks for
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except TIMING_ERRORS as exc:
            log.warning("token refused (%s): %s", type(exc).__name__, _seconds_off(token))
            AUTH_REFUSALS.labels("clock_or_expiry").inc()
            return None
        except jwt.PyJWTError as exc:
            log.warning("token refused (%s)", type(exc).__name__)
            AUTH_REFUSALS.labels("invalid_token").inc()
            return None

        lifetime = claims["exp"] - claims["iat"]
        if lifetime > self._max_lifetime:  # a token meant to live long should not exist
            log.warning("token refused (lifetime %ss exceeds the %ss cap)", lifetime, self._max_lifetime)
            AUTH_REFUSALS.labels("lifetime_too_long").inc()
            return None
        if not self._replay.first_use(str(claims["jti"]), claims["exp"] + self._leeway):
            log.warning("token refused (already used: replay)")
            AUTH_REFUSALS.labels("replay").inc()
            return None
        return AccessToken(
            token=token, client_id=claims["iss"], scopes=[], expires_at=int(claims["exp"]),
            subject=str(claims["sub"]), claims=claims,
        )


def build_verifier(cfg: Settings) -> ServiceJWTVerifier:
    return ServiceJWTVerifier(
        cfg.jwt_public_key_pem, cfg.mcp_jwt_issuer, cfg.mcp_jwt_audience,
        cfg.mcp_jwt_leeway_s, cfg.mcp_jwt_max_lifetime_s,
    )
