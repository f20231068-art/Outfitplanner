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
    ("Snitch", "https://www.snitch.com/products/"),
    ("The Souled Store", "https://www.thesouledstore.com/product/"),
    ("Levi's", "https://www.levi.in/products/"),
]


def mock_search(spec: ItemSpec) -> list[Product]:
    """Fake results: 3 genuine matches (60/80/95% of the cap) plus one women's-wear decoy.

    The decoy is the priciest result, so a search that skipped verification would pick it.
    """
    desc = " ".join(f"{spec.color or ''} {spec.fit or ''} {spec.item}".split())
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
                attributes={**({"color": spec.color} if spec.color else {}), "category": spec.category, "gender": "men"},
            )
        )
    # a decoy that must be rejected: a women's item, or (when the shopper asked for a colour) the wrong colour
    wrong_colour = spec.color_source == "user" and bool(spec.color)
    decoy_color = ("black" if (spec.color or "").lower() != "black" else "white") if wrong_colour else None
    products.append(
        Product(
            product_id=f"mock-{seed}-decoy",
            title=f"{(decoy_color or 'Women').title()} {spec.item.title()}",
            retailer="Bewakoof",
            price_inr=int(spec.max_price_inr * 0.99),
            url=f"https://www.bewakoof.com/p/decoy-{query}",
            image_url=f"https://placehold.co/400x500?text=Bewakoof-{seed}",
            color=decoy_color,
            description=f"{decoy_color or 'women'} {spec.item}",
            attributes={
                **({"color": decoy_color} if decoy_color else {}),
                "category": spec.category,
                "gender": "men" if decoy_color else "women",
            },
        )
    )
    return products
