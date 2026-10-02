"""One-time setup for the local observability stack.

    python scripts/init_observability.py

Creates a METRICS_TOKEN (the password Prometheus uses to read /metrics from the API and the tool server)
in the repo-root .env, and writes the same token to infra/observability/.secrets/metrics_token, which
Prometheus mounts. Both places are git-ignored. Re-running keeps the existing token.
"""

import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
SECRET = ROOT / "infra" / "observability" / ".secrets" / "metrics_token"

text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
match = re.search(r"^METRICS_TOKEN=(.+)$", text, flags=re.MULTILINE)
token = match.group(1).strip() if match else secrets.token_urlsafe(32)
if not match:
    text = re.sub(r"^METRICS_TOKEN=.*\n?", "", text, flags=re.MULTILINE).rstrip("\n")
    text += f"\n\n# Prometheus reads /metrics with this token (see infra/observability)\nMETRICS_TOKEN={token}\n"
    ENV.write_text(text, encoding="utf-8")

SECRET.parent.mkdir(parents=True, exist_ok=True)
SECRET.write_text(token, encoding="utf-8")  # no trailing newline: Prometheus uses the file's exact contents
print("METRICS_TOKEN is set in .env" + (" (kept the existing one)" if match else " (newly generated)"))
print(f"wrote {SECRET.relative_to(ROOT)} (git-ignored)")
