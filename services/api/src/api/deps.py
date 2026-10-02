"""Things endpoints ask for: the logged-in user, a database connection, a rate limit."""

import json

from fastapi import HTTPException, Request

from api.security.throttle import SlidingWindow, TooManyAttempts
from api.security.tokens import Identity, InvalidToken, verify_access_token
from api.telemetry import RATE_LIMITED


def current_user(request: Request) -> Identity:
    """The caller's identity, taken from a valid access token. 401 for anything else, with the same
    message every time so a failure says nothing about why."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    try:
        if scheme.lower() != "bearer" or not token:
            raise InvalidToken
        return verify_access_token(token, request.app.state.cfg)
    except InvalidToken:
        raise HTTPException(401, "Please log in.", headers={"WWW-Authenticate": "Bearer"}) from None


def enforce(limiter: SlidingWindow, key: str) -> None:
    """Apply a rate limit, answering 429 with a Retry-After header when it is exceeded."""
    try:
        limiter.check(key)
    except TooManyAttempts as exc:
        RATE_LIMITED.labels(getattr(limiter, "name", "other")).inc()
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after_s)}) from exc


def client_ip(request: Request) -> str:
    # Behind a proxy this would be the proxy's address; reading X-Forwarded-For is only safe when
    # the proxy is trusted, so that is configured at deployment time, not assumed here.
    return request.client.host if request.client else "unknown"


def sse(event: str, data: dict) -> str:
    """One server-sent event. JSON never contains a raw newline, so the framing cannot be broken
    by anything inside the data."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
