"""Complete .env.production for the hosted layout (docker-compose.prod.yml). Run after
`generate_jwt_keys.py --out .env.production`. Never prints a secret.

    python scripts/init_production_env.py             # local test on http://localhost:8080
    python scripts/init_production_env.py --server demo.example.com   # a real server with https

It adds only what is missing: a random database password, the address settings, and (as a convenience for
local testing) copies of the model/search keys from your .env. For a real server, put NEW keys in
.env.production by hand instead.
"""

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env.production"
COPY_FROM_DOTENV = ["STYLIST_MODEL", "OPENROUTER_API_KEY", "SERPAPI_API_KEY", "ADMIN_EMAILS"]


def values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {m.group(1): m.group(2) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", path.read_text(encoding="utf-8"), re.M)}


def main() -> None:
    args = sys.argv[1:]
    server = args[args.index("--server") + 1] if "--server" in args else ""
    have = values(TARGET)
    if "MCP_JWT_PUBLIC_KEY" not in have:
        sys.exit("No signing keys yet. Run: uv run --project services/mcp python scripts/generate_jwt_keys.py --out .env.production")
    add: dict[str, str] = {}
    if not have.get("POSTGRES_PASSWORD"):
        add["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
    if server:
        add.update(SITE_ADDRESS=server, PUBLIC_URL=f"https://{server}")
    else:  # laptop test: plain http on a port that is unlikely to be taken
        add.update(SITE_ADDRESS=":80", PUBLIC_URL="http://localhost:8080", HTTP_PORT="8080", COOKIE_SECURE="false")
    dotenv = values(ROOT / ".env")
    for name in COPY_FROM_DOTENV:
        if dotenv.get(name):
            add[name] = dotenv[name]
    new = {k: v for k, v in add.items() if not have.get(k)}
    if new:
        text = TARGET.read_text(encoding="utf-8").rstrip("\n")
        TARGET.write_text(text + "\n\n" + "\n".join(f"{k}={v}" for k, v in new.items()) + "\n", encoding="utf-8")
    print("added:", ", ".join(new) or "nothing (already complete)")
    missing = [k for k in ("OPENROUTER_API_KEY", "SERPAPI_API_KEY") if not (have.get(k) or new.get(k))]
    if missing:
        print("still empty (fill in by hand):", ", ".join(missing))


if __name__ == "__main__":
    main()
