"""The API's side of the MCP login: tokens it signs must be short-lived, unique and request-fresh."""

import httpx2
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from api.config import Settings
from api.mcp_auth import ServiceTokenAuth, mint_service_token

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE = _key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
PUBLIC = _key.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
ARGS = {"private_key_pem": PRIVATE, "issuer": "stylist-api", "audience": "stylist-mcp"}


def decode(token: str) -> dict:
    return jwt.decode(token, PUBLIC, algorithms=["RS256"], audience="stylist-mcp", issuer="stylist-api")


def test_a_minted_token_verifies_with_the_public_key_and_carries_the_user():
    claims = decode(mint_service_token("user_42", **ARGS))
    assert claims["sub"] == "user_42" and claims["iss"] == "stylist-api" and claims["aud"] == "stylist-mcp"


def test_a_token_lives_for_the_ttl_only():
    claims = decode(mint_service_token("u", ttl_s=30, **ARGS))
    assert claims["exp"] - claims["iat"] == 30


def test_every_token_has_its_own_unique_id():
    ids = {decode(mint_service_token("u", **ARGS))["jti"] for _ in range(50)}
    assert len(ids) == 50


def test_a_token_holds_no_secret_material():
    token = mint_service_token("u", **ARGS)
    assert "PRIVATE" not in token and set(decode(token)) == {"iss", "aud", "sub", "iat", "exp", "jti"}


def test_the_public_key_cannot_be_used_to_sign():
    with pytest.raises(Exception):  # noqa: B017 - signing with a public key must fail in any way
        jwt.encode({"sub": "x"}, PUBLIC, algorithm="RS256")


def test_each_http_request_gets_a_different_token():
    cfg = Settings(mcp_jwt_private_key=PRIVATE, _env_file=None)
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers["authorization"])
        return httpx2.Response(200)

    with httpx2.Client(transport=httpx2.MockTransport(handler), auth=ServiceTokenAuth("user_42", cfg)) as c:
        for _ in range(3):
            c.get("https://mcp.test/mcp")
    tokens = [h.removeprefix("Bearer ") for h in seen]
    assert len(set(tokens)) == 3  # a new token per request
    assert all(decode(t)["sub"] == "user_42" for t in tokens)


def test_a_key_stored_on_one_line_with_literal_backslash_n_works():
    cfg = Settings(mcp_jwt_private_key=PRIVATE.strip().replace("\n", "\\n"), _env_file=None)
    token = mint_service_token("u", private_key_pem=cfg.jwt_private_key_pem, issuer="stylist-api", audience="stylist-mcp")
    assert decode(token)["sub"] == "u"


def test_signing_refuses_to_run_without_a_private_key():
    with pytest.raises(RuntimeError, match="MCP_JWT_PRIVATE_KEY"):
        ServiceTokenAuth("u", Settings(mcp_jwt_private_key="", _env_file=None))
