"""The stores the stylist may search and link to: 100 menswear brands, generated from docs/niche-sellers.md.

A store belongs to one GROUP. After the shopper picks a style the agent chooses which groups to search, so a
streetwear look does not spend its search on ethnic or denim specialists. Domains are the only thing sent to
the search provider (include_domains) and the only hosts the link tools will open.
"""

from dataclasses import dataclass
from typing import Literal

GROUPS = ('streetwear', 'smart_casual', 'denim', 'traditional', 'activewear')

StoreGroup = Literal[GROUPS]  # the values a caller may pass as store_groups

GROUP_LABELS = {
    "streetwear": "Streetwear and Gen-Z casual: tees, hoodies, cargos, oversized fits",
    "smart_casual": "Smart casual, shirts, linen, formal and premium labels (incl. global labels sold in India)",
    "denim": "Denim specialists: jeans and denim casuals",
    "traditional": "Traditional, ethnic, handloom and sustainable: kurtas, sherwanis, nehru jackets, khadi",
    "activewear": "Innerwear, loungewear, activewear and outdoor",
}


@dataclass(frozen=True)
class Seller:
    brand: str
    domain: str
    group: str
    sells: str


SELLERS: tuple[Seller, ...] = (
    Seller('Snitch', 'snitch.com', 'streetwear', 'Trend-led shirts, tees, jeans, jackets (Bengaluru)'),
    Seller('Bonkers Corner', 'bonkerscorner.com', 'streetwear', 'Unisex streetwear, oversized tees, cargos'),
    Seller('The Souled Store', 'thesouledstore.com', 'streetwear', 'Licensed pop-culture tees, hoodies, joggers'),
    Seller('Bewakoof', 'bewakoof.com', 'streetwear', 'Quirky graphic tees, hoodies, joggers, budget casuals'),
    Seller('Urban Monkey', 'urbanmonkey.com', 'streetwear', 'Streetwear, caps, oversized tees'),
    Seller('Veirdo', 'veirdo.in', 'streetwear', 'Printed shirts, tees, oversized fits'),
    Seller('Nobero', 'nobero.com', 'streetwear', 'Everyday tees, hoodies, joggers'),
    Seller('Hello Swanky', 'helloswanky.com', 'streetwear', 'Indian streetwear, tees, hoodies'),
    Seller('Farak', 'farak.co', 'streetwear', 'Handmade streetwear label'),
    Seller('VegNonVeg', 'vegnonveg.com', 'streetwear', 'Multi-brand streetwear and sneaker boutique'),
    Seller('Warping Theories', 'warpingtheories.com', 'streetwear', 'Modern menswear, utility cargos, hoodies'),
    Seller('Nought One', 'noughtone.in', 'streetwear', 'Delhi street label, technical fabrics, unusual silhouettes'),
    Seller('Almost Gods', 'almostgods.in', 'streetwear', 'Delhi streetwear rooted in Indian heritage'),
    Seller('Bluorng', 'bluorng.com', 'streetwear', 'Casual and streetwear shirts, tees'),
    Seller('Khaaki', 'khaaki.in', 'streetwear', 'Premium Indian streetwear'),
    Seller('Fugazee', 'fugazee.com', 'streetwear', 'Streetwear tees, hoodies, bottoms'),
    Seller('Kook N Keech', 'kooknkeech.com', 'streetwear', 'Graphic tees, hoodies, jeans, pants'),
    Seller('Jaywalking', 'jaywalking.in', 'streetwear', 'Oversized, deconstructed street designs'),
    Seller('The Dry State', 'thedrystate.com', 'streetwear', 'Streetwear and casuals'),
    Seller('Wrogn', 'wrogn.com', 'streetwear', 'Casual shirts, tees, denim (Virat Kohli label)'),
    Seller('Rigo', 'rigo.in', 'streetwear', 'Casual tees, shirts, bottoms'),
    Seller('MyDesignation', 'mydesignation.com', 'streetwear', 'Casual shirts and tees'),
    Seller('Tistabene', 'tistabene.com', 'streetwear', 'Youth casuals'),
    Seller('Beyoung', 'beyoung.in', 'streetwear', 'Budget youth casuals, tees, joggers'),
    Seller('Bummer', 'bummer.in', 'streetwear', 'Underwear, loungewear, casual basics'),
    Seller('Cahoot', 'cahoot.in', 'streetwear', "Oversized and check shirts, jeans (Campus Sutra's new store)"),
    Seller('Lymio', 'lymio.in', 'streetwear', 'Budget casual shirts, tees, trousers'),
    Seller('Pronk', 'pronk.in', 'streetwear', 'Casual wear'),
    Seller('Dillinger', 'dillinger.in', 'streetwear', 'Unisex casuals, oversized tees, jeans'),
    Seller('Zobello', 'zobello.com', 'streetwear', 'Casual shirts, blazers, jackets, shorts, footwear'),
    Seller('Rare Rabbit', 'thehouseofrare.com', 'smart_casual', 'Premium casual and occasion menswear (The House of Rare)'),
    Seller('Powerlook', 'powerlook.in', 'smart_casual', 'Affordable trend-driven shirts, trousers'),
    Seller('Andamen', 'andamen.com', 'smart_casual', 'Premium shirts with Indian-motif prints, pants, tees'),
    Seller('Bombay Shirt Company', 'bombayshirts.com', 'smart_casual', 'Made-to-measure shirts, blazers, pants'),
    Seller('The Pant Project', 'pantproject.com', 'smart_casual', 'Custom-fit trousers and ready-to-wear'),
    Seller('Derris', 'derris.in', 'smart_casual', 'Premium shirts, Irish-linen range, sizes to 5XL'),
    Seller('Linen Trail', 'linentrail.com', 'smart_casual', '100 percent linen shirts, trousers, kurtas'),
    Seller('Bhrata', 'bhrata.com', 'smart_casual', 'Pure-linen menswear'),
    Seller('Mr Button', 'mrbutton.in', 'smart_casual', 'Shirts, blazers, suits'),
    Seller('The Bear House', 'thebearhouse.com', 'smart_casual', 'Casual and smart-casual shirts, tees'),
    Seller('Dennis Lingo', 'dennislingo.com', 'smart_casual', 'Smart-casual shirts, chinos'),
    Seller('Zodiac', 'zodiaconline.com', 'smart_casual', 'Formal shirts, trousers, accessories'),
    Seller('Turtle', 'turtle.in', 'smart_casual', 'Shirts, trousers, casual wear'),
    Seller('Monte Carlo', 'montecarlo.in', 'smart_casual', 'Knitwear, sweaters, winterwear, casuals'),
    Seller('Being Human', 'beinghumanclothing.com', 'smart_casual', 'Casual tees, shirts, jeans (Salman Khan label)'),
    Seller('Cottonworld', 'cottonworld.net', 'smart_casual', 'Natural cotton and linen clothes'),
    Seller('Rathore', 'rathore.com', 'smart_casual', 'Luxury bespoke menswear, Jodhpuri suits'),
    Seller('Blackberrys', 'blackberrys.com', 'smart_casual', 'Formal and wedding suits, shirts'),
    Seller('Indian Terrain', 'indianterrain.com', 'smart_casual', 'Smart-casual shirts, chinos, tees'),
    Seller('Celio', 'celio.in', 'smart_casual', 'Casual shirts, tees, jeans (French label)'),
    Seller('Raymond', 'myraymond.com', 'smart_casual', 'Suiting, formalwear, Park Avenue, ColorPlus, Parx'),
    Seller('Allen Solly', 'allensolly.com', 'smart_casual', 'Smart-casual and Friday dressing (redirects to abfrl.in)'),
    Seller('Van Heusen', 'vanheusenindia.com', 'smart_casual', 'Business formal and smart casual (redirects to abfrl.in)'),
    Seller('Louis Philippe', 'louisphilippe.com', 'smart_casual', 'Premium formal and luxury suiting (redirects to abfrl.in)'),
    Seller('Peter England', 'peterengland.com', 'smart_casual', 'Value formal and casual (redirects to abfrl.in)'),
    Seller('U.S. Polo Assn.', 'uspoloassn.in', 'smart_casual', 'Polos, tees, casual shirts, chinos'),
    Seller('Jack & Jones', 'jackjones.in', 'smart_casual', 'Western casual, tees, jeans, jackets'),
    Seller("Levi's", 'levi.in', 'smart_casual', 'Jeans, tees, jackets'),
    Seller('Superdry', 'superdry.in', 'smart_casual', 'Jackets, hoodies, tees'),
    Seller('Gant', 'gant.in', 'smart_casual', 'Preppy premium casual and shirts'),
    Seller('Marks & Spencer', 'marksandspencer.in', 'smart_casual', 'Basics, shirts, chinos, knitwear'),
    Seller('Spykar', 'spykar.com', 'denim', 'Jeans, shirts, casuals'),
    Seller('Killer Jeans', 'killerjeans.com', 'denim', 'Jeans, shirts, tees'),
    Seller('Mufti', 'muftijeans.in', 'denim', 'Casual menswear and denim'),
    Seller('Pepe Jeans', 'pepejeans.in', 'denim', 'Jeans, tees, jackets'),
    Seller('Wrangler', 'wrangler.in', 'denim', 'Jeans, tees, shirts'),
    Seller('Voi Jeans', 'voijeans.com', 'denim', "Premium men's denim and urban casuals"),
    Seller('Lawman PG3', 'lawmanpg3.com', 'denim', 'Tees, shirts, denims, cargos, jackets'),
    Seller('Manyavar', 'manyavar.com', 'traditional', 'Wedding sherwanis, kurta sets, Nehru jackets'),
    Seller('Tasva', 'tasva.com', 'traditional', 'Wedding wear, sherwanis, kurtas'),
    Seller('Vastramay', 'vastramay.com', 'traditional', 'Kurta sets, sherwanis, Indo-western'),
    Seller('Kalpraag', 'kalpraag.com', 'traditional', 'Luxury kurta sets, Jodhpuri, Indo-western wedding looks'),
    Seller('Shreeman', 'shreeman.in', 'traditional', 'Sherwanis and kurtas, affordable designer'),
    Seller('Kalki Fashion', 'kalkifashion.com', 'traditional', 'Kurtas, sherwanis, wedding wear'),
    Seller('Samyakk', 'samyakk.com', 'traditional', 'Sherwanis, kurtas, ethnic wear'),
    Seller('Utsav Fashion', 'utsavfashion.com', 'traditional', 'Large ethnic range: kurta pajama, dhoti, sherwani'),
    Seller('Kisah', 'kisah.in', 'traditional', 'Wedding and festive ethnic wear'),
    Seller('Sojanya', 'sojanya.com', 'traditional', "Men's ethnic wear"),
    Seller('Mohanlal Sons', 'mohanlalsons.com', 'traditional', 'Kurtas, designer wedding outfits'),
    Seller('Fabindia', 'fabindia.com', 'traditional', 'Handloom cotton kurtas, Nehru jackets, linen trousers'),
    Seller('Ramraj Cotton', 'ramrajcotton.in', 'traditional', 'Veshti and dhoti, shirts (Tamil Nadu)'),
    Seller('Jaypore', 'jaypore.com', 'traditional', 'Handcrafted and artisanal Indian wear (multi-brand)'),
    Seller('Aza Fashions', 'azafashions.com', 'traditional', 'Designer menswear and ethnic (multi-designer)'),
    Seller("Pernia's Pop-Up Shop", 'perniaspopupshop.com', 'traditional', 'Designer ethnic and occasion wear (multi-designer)'),
    Seller('Nicobar', 'nicobar.com', 'traditional', 'Modern India-rooted resort and linen casuals'),
    Seller('Kharakapas', 'kharakapas.com', 'traditional', 'Pure-cotton handcrafted Indian shirts and kurtas'),
    Seller('No Nasties', 'nonasties.in', 'traditional', 'Organic-cotton tees and basics'),
    Seller('Khadi India', 'ekhadiindia.com', 'traditional', 'Official khadi portal: kurtas, shirts, jackets'),
    Seller('GoSwadeshi (GoCoop)', 'goswadeshi.in', 'traditional', 'Handloom marketplace, khadi and weaver co-ops'),
    Seller('Ethnicity', 'ethnicity.in', 'traditional', 'Contemporary Indian wear for men, women and kids'),
    Seller('Cottons Jaipur', 'cottonsjaipur.com', 'traditional', 'Hand-block-printed cotton shirts'),
    Seller('XYXX', 'xyxxcrew.com', 'activewear', 'Innerwear, loungewear, athleisure'),
    Seller('Damensch', 'damensch.com', 'activewear', 'Innerwear, loungewear, activewear, tees'),
    Seller('Jockey', 'jockey.in', 'activewear', 'Innerwear, loungewear, tees'),
    Seller('FREECULTR', 'freecultr.com', 'activewear', 'Innerwear, loungewear, essentials'),
    Seller('Puma India', 'in.puma.com', 'activewear', 'Sportswear, tees, track pants'),
    Seller('Reebok India', 'reebok.in', 'activewear', 'Sportswear and fitness apparel (redirects to abfrl.in)'),
    Seller('Technosport', 'technosport.in', 'activewear', 'Performance activewear, athleisure'),
    Seller('Boldfit', 'boldfit.com', 'activewear', 'Gym wear and activewear'),
    Seller('Decathlon India', 'decathlon.in', 'activewear', 'Sports and outdoor apparel'),
)

# Stores that redirect to this host: it must be allowed too, or the link check reports 'redirected_off_domain'.
REDIRECT_TARGET_DOMAINS = ("abfrl.in",)

ALL_DOMAINS: tuple[str, ...] = tuple(s.domain for s in SELLERS) + REDIRECT_TARGET_DOMAINS


def domains_for(groups) -> list[str]:
    """The domains of the given groups (all of them if none are given), without repeats, in list order."""
    wanted = set(groups or GROUPS)
    return [s.domain for s in SELLERS if s.group in wanted]


def seller_for_host(host: str) -> Seller | None:
    """The store a host belongs to (a subdomain counts), or None if it is not on the list."""
    host = (host or "").lower().removeprefix("www.")
    return next((s for s in SELLERS if host == s.domain or host.endswith("." + s.domain)), None)
