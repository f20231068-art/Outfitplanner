"""Rules every tool must follow, checked automatically so a future tool cannot quietly break them.

If you add a tool, add a line to SAMPLE_ARGS; the test below fails until you do.
"""

import json
import re

import httpx
from fastmcp import Client

from mcp_server.config import Settings
from mcp_server.providers.serpapi import DetailRef, parse_offers, parse_shopping_results
from mcp_server.server import build_server
from tests.keys import PUBLIC_PEM

from .test_buy_link import OFFERS

CFG = Settings(serpapi_api_key="x", mcp_jwt_public_key=PUBLIC_PEM, _env_file=None)
NAME_RULE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")  # the spec's allowed tool-name characters


class FakeProvider:
    def __init__(self, response):
        self.response = response

    async def search(self, query):
        parsed, skipped = parse_shopping_results(self.response)
        for p in parsed:
            p.detail_ref = DetailRef("https://detail.test/x?t=1", p.product.title, p.product.retailer)
        return parsed, skipped

    async def offers(self, ref):
        return parse_offers(OFFERS)


async def _public(host):
    return ["104.18.2.2"]


async def test_every_tool_is_well_formed_and_returns_both_forms(chinos_response):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<title>ok</title>")))
    server = build_server(CFG, provider=FakeProvider(chinos_response), http_client=http, resolver=_public)

    async with Client(server) as c:
        found = (await c.call_tool("search_products", {"item": "chinos", "color": "beige", "max_price_inr": 99999})
                 ).structured_content
        sample_args = {
            "ping": {},
            "search_products": {"item": "chinos", "color": "beige", "max_price_inr": 5000},
            "get_buy_link": {"product_id": found["results"][0]["product_id"]},
            "check_link": {"url": "https://www.myntra.com/x/1/buy"},
        }
        tools = await c.list_tools()
        names = [t.name for t in tools]

        assert set(names) == set(sample_args), "a tool was added or removed: update sample_args"
        assert len(names) == len(set(names)), "tool names must be unique"

        for t in tools:
            assert NAME_RULE.match(t.name), t.name
            assert t.description and len(t.description) > 10, f"{t.name} needs a real description"
            assert t.output_schema is not None, f"{t.name} must declare an output type"
            assert t.annotations and t.annotations.read_only_hint is True
            for prop, spec in t.input_schema.get("properties", {}).items():
                assert spec.get("description"), f"{t.name}.{prop} needs a description"

            result = await c.call_tool(t.name, sample_args[t.name])
            assert result.structured_content is not None, f"{t.name}: no structured result"
            assert result.content and result.content[0].type == "text", f"{t.name}: no text result"
            # the text form must carry the same data as the structured form
            text = result.content[0].text
            if t.name == "ping":
                assert text == "pong"
            else:
                assert json.loads(text) == result.structured_content, f"{t.name}: forms differ"
