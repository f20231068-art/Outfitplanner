"""Guards against the mistake that is easiest to make: a real secret ending up in a file that gets
committed. `.env.example` is committed on purpose, so it must hold names and harmless defaults only."""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SECRET_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)")
# Documented local-development defaults that are not secrets (and must be changed when deploying)
HARMLESS_DEFAULTS = {"POSTGRES_PASSWORD": "stylist_dev_password"}
KEY_SHAPES = re.compile(r"sk-or-v1-[0-9a-f]{20,}|sk-[A-Za-z0-9]{32,}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


def test_the_example_env_file_holds_no_real_secret_values():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    leaked = []
    for line in example.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        has_value = m and SECRET_NAME.search(m[1]) and m[2].strip().strip('"')
        if has_value and HARMLESS_DEFAULTS.get(m[1]) != m[2].strip():
            leaked.append(m[1])  # names only: never print the value
    assert not leaked, f".env.example has values for: {leaked}. Empty them; real values belong in .env only."


def _committable_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    return [ROOT / f for f in out.splitlines() if f]


def test_no_file_that_git_could_commit_contains_a_key_shaped_string():
    offenders = []
    for f in _committable_files():
        if f.suffix in {".png", ".jpg", ".ico", ".lock", ".json"} and f.name != "package.json":
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if f.name == "test_repo_hygiene.py":
            continue  # this file contains the patterns themselves
        if KEY_SHAPES.search(text):
            offenders.append(str(f.relative_to(ROOT)))
    assert not offenders, f"key-shaped text found in: {offenders}"


def test_the_real_env_file_is_ignored_by_git():
    result = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT, check=False)
    assert result.returncode == 0, ".env must be in .gitignore"
