"""Stand-ins for the search provider and the page reader, so tests never touch the network or spend a credit."""

from mcp_server.providers.page_facts import PageFacts
from mcp_server.providers.tavily import parse_results


class FakeTavily:
    """Returns a saved REAL Tavily response through the real parser, and remembers what it was asked."""

    def __init__(self, response: dict, credits: int = 1):
        self.response, self.credits_per_search = response, credits
        self.calls, self.last_query, self.last_domains = 0, None, None

    async def search(self, query: str, domains: list[str]):
        self.calls += 1
        self.last_query, self.last_domains = query, domains
        return parse_results(self.response, credits=self.credits_per_search)


def default_facts(url: str) -> PageFacts:
    """Plausible facts for any page: a price that depends on the address, so different pages differ."""
    n = sum(map(ord, url)) % 40
    return PageFacts(name=f"Page product {n}", price_inr=800 + n * 25, image_url=f"https://img.example/{n}.jpg", in_stock=True)


class FakePages:
    """A page reader. `facts` maps a URL to what the page states (None = unreadable); other URLs get default_facts."""

    def __init__(self, facts: dict | None = None):
        self.facts, self.calls = dict(facts or {}), []

    async def __call__(self, url: str):
        self.calls.append(url)
        return self.facts[url] if url in self.facts else default_facts(url)
