"""Create the RSA key pairs used for signed tokens (JWT, RS256). Keys are written into the repo-root
.env and never printed.

    uv run --project services/mcp python scripts/generate_jwt_keys.py            # create missing pairs
    uv run --project services/mcp python scripts/generate_jwt_keys.py --rotate   # replace ALL pairs
    uv run --project services/mcp python scripts/generate_jwt_keys.py --rotate auth   # replace one

Two separate pairs, so a token for one purpose can never be accepted for the other:
  mcp   API -> MCP tool server. The API signs (PRIVATE key), the MCP server verifies (PUBLIC key).
  auth  users logging in. The API signs the access tokens (PRIVATE) and verifies them (PUBLIC).

When hosting: the MCP service gets ONLY MCP_JWT_PUBLIC_KEY. The API service gets the other three.
Rotating invalidates tokens signed with the old key: restart the services that use it.
"""

import hashlib
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ENV = Path(__file__).resolve().parents[1] / ".env"
PAIRS = {
    "mcp": ("MCP_JWT_PRIVATE_KEY", "MCP_JWT_PUBLIC_KEY", "API -> MCP tool server"),
    "auth": ("AUTH_JWT_PRIVATE_KEY", "AUTH_JWT_PUBLIC_KEY", "user login tokens"),
}


def one_line(pem: bytes) -> str:  # .env values are single-line; the \n markers are expanded when loaded
    return pem.decode().strip().replace("\n", "\\n")


def has_value(text: str, name: str) -> bool:
    return bool(re.search(rf"^{name}=.+", text, flags=re.MULTILINE))


def main() -> None:
    args = sys.argv[1:]
    rotate = "--rotate" in args
    chosen = [a for a in args if a in PAIRS] or list(PAIRS)
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""

    for name in chosen:
        private_var, public_var, purpose = PAIRS[name]
        if has_value(text, private_var) and has_value(text, public_var) and not rotate:
            print(f"{name}: already present, left alone (use --rotate to replace)")
            continue
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        for var in (private_var, public_var):  # drop old lines (single-line values only)
            text = re.sub(rf"^{var}=.*\n?", "", text, flags=re.MULTILINE)
        text = text.rstrip("\n") + (
            f"\n\n# {purpose}: RS256 key pair. The PRIVATE key stays with the signer only.\n"
            f'{private_var}="{one_line(private)}"\n{public_var}="{one_line(public)}"\n'
        )
        print(f"{name}: new key pair written (fingerprint {hashlib.sha256(public).hexdigest()[:16]})")

    ENV.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
