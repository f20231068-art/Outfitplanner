import os

# Most tests exercise the ranked-results (Tavily) search through a fake; the model search has its own tests.
os.environ.setdefault("SEARCH_PROVIDER", "tavily")

import json
from pathlib import Path

import pytest

from tests.fakes import FakePages

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def tavily_response() -> dict:
    """A REAL Tavily Search response (captured 2026-10-05) for 'blue polo t-shirt for men' over the streetwear and
    smart-casual stores: 20 pages, of which 13 are product pages on approved stores."""
    return load("tavily_polo.json")


@pytest.fixture
def tavily_chinos() -> dict:
    return load("tavily_chinos.json")


@pytest.fixture
def tavily_tee() -> dict:
    return load("tavily_tee.json")


@pytest.fixture(autouse=True)
def no_real_page_reads(monkeypatch):
    """Safety net: a test that builds a server without injecting a page reader must never reach the network."""
    async def fake(url, cfg, client, resolver=None):
        return await FakePages()(url)

    monkeypatch.setattr("mcp_server.server.read_page", fake)
