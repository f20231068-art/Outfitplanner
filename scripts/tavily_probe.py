"""Run the REAL search pipeline on real queries and report what the agent would get.

    uv run --project services/mcp python scripts/tavily_probe.py                    # the 3 default queries
    uv run --project services/mcp python scripts/tavily_probe.py --save             # also save each Tavily response as a fixture
    uv run --project services/mcp python scripts/tavily_probe.py -q "linen shirt for men" -g smart_casual
    uv run --project services/mcp python scripts/tavily_probe.py --depth advanced   # try other Tavily options

Each query costs 1 Tavily credit (2 if --depth advanced). Reading the stores' own product pages is free.
It reads TAVILY_API_KEY from the repo-root .env and never prints it. It uses the SAME code the tool server uses.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")

from mcp_server.cache import TTLCache  # noqa: E402
from mcp_server.config import Settings  # noqa: E402
from mcp_server.net import make_client, post_json  # noqa: E402
from mcp_server.providers.page_facts import read_page  # noqa: E402
from mcp_server.providers.tavily import TavilySearch  # noqa: E402
from mcp_server.sellers import GROUPS  # noqa: E402
from mcp_server.tools.search_products import run_search  # noqa: E402

DEFAULT_QUERIES = [
    ("polo t-shirt", "blue", ["streetwear", "smart_casual"]),
    ("chinos", "beige", ["smart_casual"]),
    ("oversized t-shirt", "black", ["streetwear"]),
]


def read_key() -> str:
    text = (ROOT / ".env").read_text(encoding="utf-8") if (ROOT / ".env").exists() else ""
    m = re.search(r"^TAVILY_API_KEY=(.*)$", text, re.M)
    key = (m.group(1) if m else "").strip().strip('"')
    if not key:
        sys.exit("TAVILY_API_KEY is empty in .env. Put your key there (it is git-ignored) and run again.")
    return key


async def probe(item: str, color: str | None, groups: list[str], cfg: Settings, client, save: Path | None) -> int:
    provider = TavilySearch(cfg, client)
    captured: dict = {}

    class Recording:  # the same provider, remembering the raw response when asked to save it
        credits_per_search = provider.credits_per_search

        async def search(self, query, domains):
            if save:
                data = await post_json(client, cfg.tavily_base_url, provider.request_body(query, domains),
                                       {"Authorization": f"Bearer {cfg.tavily_api_key}"})
                captured.update(data)
                from mcp_server.providers.tavily import parse_results

                return parse_results(data, credits=int((data.get("usage") or {}).get("credits") or provider.credits_per_search))
            return await provider.search(query, domains)

    async def reader(url):
        return await read_page(url, cfg, client)

    started = time.perf_counter()
    out = await run_search(
        Recording(), TTLCache(60), TTLCache(60), cfg, item=item, color=color, max_price_inr=99999, store_groups=groups,
        page_reader=reader, facts_cache=TTLCache(60), failed_cache=TTLCache(60),
    )
    secs = time.perf_counter() - started

    print(f"\n=== {out.query_used!r}  groups={out.store_groups} ({out.stores_searched} stores)  depth={cfg.tavily_search_depth}")
    print(f"    credits used: {out.credits_spent} | {out.pages_read} candidate pages read | {len(out.results)} usable products | {secs:.1f}s in total")
    print("    left out:", ", ".join(f"{w.count} {w.code}" for w in out.warnings) or "nothing")
    with_img = sum(bool(p.image_url) for p in out.results)
    print(f"    usable products with an image: {with_img} of {len(out.results)} | stores: "
          f"{sorted({p.retailer for p in out.results})}")
    for p in out.results[:8]:
        print(f"      {p.retailer:<18} Rs {p.price_inr:<6} stock={p.in_stock} img={'yes' if p.image_url else 'NO '} rel={p.relevance} "
              f"colour={p.attributes.get('color', '-')} | {p.title[:55]}")
    if save and captured:
        save.mkdir(parents=True, exist_ok=True)
        slim = {"query": captured.get("query"), "usage": captured.get("usage"),
                "results": [{k: r.get(k) for k in ("url", "title", "content", "score")} for r in captured.get("results", [])]}
        path = save / f"tavily_real_{re.sub(r'[^a-z0-9]+', '_', out.query_used.lower()).strip('_')[:40]}.json"
        path.write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    saved the Tavily response to {path.relative_to(ROOT)}")
    return out.credits_spent


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-q", "--query", help="one garment instead of the 3 defaults, e.g. 'linen shirt'")
    ap.add_argument("-c", "--color", default=None)
    ap.add_argument("-g", "--groups", nargs="+", choices=GROUPS, default=["streetwear", "smart_casual"])
    ap.add_argument("--depth", default="basic", choices=["basic", "fast", "ultra-fast", "advanced"])
    ap.add_argument("--max", type=int, default=20, help="max_results (0-20)")
    ap.add_argument("--reads", type=int, default=8, help="how many candidate pages to read per search")
    ap.add_argument("--country", default="", help='e.g. "india"')
    ap.add_argument("--save", action="store_true", help="save each Tavily response under services/mcp/tests/fixtures/")
    args = ap.parse_args()

    cfg = Settings(tavily_api_key=read_key(), tavily_search_depth=args.depth, tavily_max_results=args.max,
                   tavily_country=args.country, page_reads_per_search=args.reads, _env_file=None)
    queries = [(args.query, args.color, args.groups)] if args.query else DEFAULT_QUERIES
    save = ROOT / "services" / "mcp" / "tests" / "fixtures" if args.save else None
    total = 0
    async with make_client(cfg) as client:
        for item, color, groups in queries:
            try:
                total += await probe(item, color, groups, cfg, client, save)
            except Exception as exc:  # the message never holds the key (it travels in a header)
                print(f"\n=== {item!r}: failed: {type(exc).__name__}: {exc}")
    print(f"\nTotal Tavily credits used by this run: {total}")


if __name__ == "__main__":
    asyncio.run(main())
