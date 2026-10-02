"""Signs the tokens that prove to the MCP server that a request comes from this API.

A brand-new token is minted for EVERY outgoing HTTP request (one MCP tool call is several
requests). Each token has a unique id and lives 30 seconds, and the MCP server accepts each id
only once, so a copy of a token that leaks is useless after the real request has used it.
Signing an RSA token takes about a millisecond, so minting per request costs nothing noticeable.

The private key stays in this service only. The MCP server only ever sees the public key.
"""

import time
import uuid
from collections.abc import Generator

import httpx2  # FastMCP 4 clients use httpx2, not httpx: the auth class must come from there
import jwt

from api.config import Settings, settings


def mint_service_token(
    subject: str,
    *,
    private_key_pem: str,
    issuer: str,
    audience: str,
    ttl_s: int = 30,
    now: float | None = None,
) -> str:
    """Create one signed token. `subject` is the end user this call is made for (used by the MCP
    server for per-user limits and the audit log). Never put secrets in a token: it is signed,
    not encrypted, so anyone holding it can read it."""
    issued = int(now if now is not None else time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": issued,
        "exp": issued + ttl_s,
        "jti": uuid.uuid4().hex,  # unique per token; the MCP server accepts each id once
    }
    return jwt.encode(claims, private_key_pem, algorithm="RS256")


class ServiceTokenAuth(httpx2.Auth):
    """Plug into the MCP client: `Client(url, auth=ServiceTokenAuth(user_id))`. httpx2 calls
    auth_flow once per request, so every request carries a different token."""

    def __init__(self, subject: str, cfg: Settings = settings):
        if not cfg.jwt_private_key_pem:
            raise RuntimeError("MCP_JWT_PRIVATE_KEY is empty. Run scripts/generate_jwt_keys.py.")
        self.subject, self.cfg = subject, cfg

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        token = mint_service_token(
            self.subject,
            private_key_pem=self.cfg.jwt_private_key_pem,
            issuer=self.cfg.mcp_jwt_issuer,
            audience=self.cfg.mcp_jwt_audience,
            ttl_s=self.cfg.mcp_jwt_ttl_s,
        )
        request.headers["Authorization"] = f"Bearer {token}"
        yield request
