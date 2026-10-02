"""Throwaway RSA keys and a token factory for tests. Never used outside the test run."""

import time
import uuid

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private, public


PRIVATE_PEM, PUBLIC_PEM = _pair()  # the "API's" keys
ATTACKER_PRIVATE_PEM, _ = _pair()  # a different key an attacker might sign with


def mint(
    sub: str = "user_42",
    *,
    key: str = PRIVATE_PEM,
    ttl: int = 30,
    skew: int = 0,  # seconds the signer's clock is AHEAD (+) or BEHIND (-) of ours
    iss: str = "stylist-api",
    aud: str = "stylist-mcp",
    jti: str | None = None,
    drop: tuple[str, ...] = (),
    algorithm: str = "RS256",
) -> str:
    now = int(time.time()) + skew
    claims = {"iss": iss, "aud": aud, "sub": sub, "iat": now, "exp": now + ttl, "jti": jti or uuid.uuid4().hex}
    for name in drop:
        claims.pop(name)
    return jwt.encode(claims, None if algorithm == "none" else key, algorithm=algorithm)
