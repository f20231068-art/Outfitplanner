"""Sign up, log in, stay logged in, log out."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from api import accounts, audit
from api.deps import client_ip, current_user, enforce
from api.security.passwords import WeakPassword
from api.security.throttle import TooManyAttempts
from api.security.tokens import Identity, mint_access_token
from api.telemetry import LOGINS

router = APIRouter(prefix="/auth", tags=["auth"])
COOKIE = "refresh_token"


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are an error, not silently ignored
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def _email_tag(email: str) -> str:
    """A short fingerprint for the audit log: lets us spot repeated attempts on one email without
    writing the email address itself into a permanent, tamper-proof record."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def _set_cookie(request: Request, response: Response, token: str) -> None:
    cfg = request.app.state.cfg
    response.set_cookie(
        COOKIE, token, max_age=cfg.auth_refresh_ttl_s, httponly=True,  # scripts cannot read it
        secure=cfg.cookie_secure, samesite="strict", path="/auth",  # sent only to /auth, only same-site
    )


def _tokens(request: Request, user_id: str) -> TokenResponse:
    cfg = request.app.state.cfg
    return TokenResponse(access_token=mint_access_token(user_id, cfg), expires_in=cfg.auth_access_ttl_s)


def _require_csrf_header(request: Request) -> None:
    """The refresh cookie rides along automatically on cross-site requests; a custom header cannot
    be added by a hostile page without a CORS permission we never give."""
    if request.headers.get("x-requested-with") != "stylist-web":
        raise HTTPException(403, "Forbidden.")


@router.post("/register", status_code=201, response_model=TokenResponse)
def register(body: Credentials, request: Request, response: Response):
    s = request.app.state
    enforce(s.ip_limiter, client_ip(request))
    with s.pool.connection() as conn:
        try:
            user_id, email = accounts.register(conn, body.email, body.password)
        except (accounts.InvalidEmail, WeakPassword) as exc:
            raise HTTPException(422, str(exc)) from exc
        except accounts.EmailTaken:
            raise HTTPException(409, "That email is already registered. Try logging in.") from None
        refresh = accounts.start_session(conn, user_id, s.cfg)
        audit.append(conn, user_id, "register", {"email_tag": _email_tag(email)})
    _set_cookie(request, response, refresh)
    return _tokens(request, user_id)


@router.post("/login", response_model=TokenResponse)
def login(body: Credentials, request: Request, response: Response):
    s = request.app.state
    ip = client_ip(request)
    enforce(s.ip_limiter, ip)
    key = f"{body.email.strip().lower()}|{ip}"
    try:
        s.login_failures.ensure_allowed(key)  # locked out after too many wrong passwords
    except TooManyAttempts as exc:
        LOGINS.labels("locked_out").inc()
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after_s)}) from exc

    with s.pool.connection() as conn:
        try:
            user_id = accounts.authenticate(conn, body.email, body.password)
        except accounts.InvalidCredentials:
            s.login_failures.record_failure(key)
            LOGINS.labels("failed").inc()
            audit.append(conn, "anonymous", "login_failed", {"email_tag": _email_tag(body.email)})
            conn.commit()  # keep the audit record even though we are about to answer 401
            raise HTTPException(401, "Invalid email or password.") from None
        s.login_failures.clear(key)
        LOGINS.labels("ok").inc()
        refresh = accounts.start_session(conn, user_id, s.cfg)
        audit.append(conn, user_id, "login", {})
    _set_cookie(request, response, refresh)
    return _tokens(request, user_id)


@router.post("/refresh", response_model=TokenResponse)
def refresh(request: Request, response: Response):
    _require_csrf_header(request)
    s = request.app.state
    enforce(s.ip_limiter, client_ip(request))
    raw = request.cookies.get(COOKIE)
    if not raw:
        raise HTTPException(401, "Please log in.")
    with s.pool.connection() as conn:
        result = accounts.rotate(conn, raw, s.cfg)
        if result.status == "reuse":  # a used token came back: someone is replaying a stolen copy
            audit.append(conn, result.user_id or "unknown", "refresh_token_reuse_detected", {})
            conn.commit()  # the revocation and the record must be saved even though we answer 401
        elif result.status == "ok":
            audit.append(conn, result.user_id, "token_refreshed", {})
    if result.status != "ok":
        response.delete_cookie(COOKIE, path="/auth")
        raise HTTPException(401, "Please log in.")
    _set_cookie(request, response, result.new_token)
    return _tokens(request, result.user_id)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    _require_csrf_header(request)
    s = request.app.state
    raw = request.cookies.get(COOKIE)
    if raw:
        with s.pool.connection() as conn:
            user_id = accounts.end_session(conn, raw)
            if user_id:
                audit.append(conn, user_id, "logout", {})
    response.delete_cookie(COOKIE, path="/auth")


@router.get("/me")
def me(request: Request, who: Identity = Depends(current_user)):
    with request.app.state.pool.connection() as conn:
        user = accounts.get_user(conn, who.user_id)
    if user is None:  # deleted or disabled since the token was issued
        raise HTTPException(401, "Please log in.")
    return {"id": str(user["id"]), "email": user["email"]}
