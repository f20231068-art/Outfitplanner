"""Product search seam.

Phase 2 uses `mock_search`. Phase 3 replaces it with a client that calls the MCP
`search_products` tool; the signature stays the same so the graph doesn't change.
Search results are untrusted: `find_products` verifies each one against the request.
"""

import hashlib
from collections.abc import Callable

from api.agent.schemas import ItemSpec, Product

ProductSearch = Callable[[ItemSpec], list[Product]]


class SearchUnavailable(Exception):
    """The shopping search could not be used right now (down, rate-limited, over its daily cap).
    The message is safe to show to the shopper."""

_RETAILERS = [
    ("Myntra", "https://www.myntra.com/search?q="),
    ("Amazon.in", "https://www.amazon.in/s?k="),
    ("Levi's", "https://www.levi.in/search?q="),
]


def mock_search(spec: ItemSpec) -> list[Product]:
    """Fake results: 3 genuine matches (60/80/95% of the cap) plus one wrong-colour decoy.

    The decoy is the priciest result, so a search that skipped verification would pick it.
    """
    desc = " ".join(f"{spec.color} {spec.fit or ''} {spec.item}".split())
    query = desc.replace(" ", "+")
    seed = hashlib.md5(query.encode()).hexdigest()[:8]
    products = []
    for (retailer, base), pct in zip(_RETAILERS, (0.6, 0.8, 0.95), strict=True):
        products.append(
            Product(
                product_id=f"mock-{seed}-{retailer.lower().replace(' ', '')[:6]}",
                title=f"Men's {desc.title()}",
                retailer=retailer,
                price_inr=int(spec.max_price_inr * pct),
                url=f"{base}{query}",
                image_url=f"https://placehold.co/400x500?text={retailer}-{seed}",
                color=spec.color,
                description=f"{desc} for everyday wear",
                attributes={"color": spec.color, "category": spec.category, "gender": "men"},
            )
        )
    decoy_color = "black" if spec.color.lower() != "black" else "white"
    products.append(
        Product(
            product_id=f"mock-{seed}-decoy",
            title=f"{decoy_color.title()} {spec.item.title()}",
            retailer="Ajio",
            price_inr=int(spec.max_price_inr * 0.99),
            url=f"https://www.ajio.com/search/?text={decoy_color}+{query}",
            image_url=f"https://placehold.co/400x500?text=Ajio-{seed}",
            color=decoy_color,
            description=f"{decoy_color} {spec.item}",
            attributes={"color": decoy_color, "category": spec.category, "gender": "men"},
        )
    )
    return products
