import json
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "serpapi_shopping_chinos.json"


@pytest.fixture
def chinos_response() -> dict:
    """A real SerpAPI Google Shopping response (trimmed to 14 results) for 'men beige chinos'."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))
