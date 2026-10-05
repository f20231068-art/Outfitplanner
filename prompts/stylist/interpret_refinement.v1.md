A shopper has been shown numbered outfits by a menswear stylist and now asks for changes. Turn their message
into a structured edit. Set only what they actually said; leave everything else empty.

- anchor: the number of the outfit they point at in the latest set ("the 3rd one" -> 3, "like the last one" ->
  the highest number). Empty if they point at none.
- relation: more_like (similar to the anchor), replace (different from what was shown), tweak (same idea,
  with changes). "Show me more like X" is more_like.
- top / bottom: changes to that piece only. A garment change goes in "item" (for example "chinos"), a colour in
  "color" (ONLY if the shopper named a colour), and "keep" is true if they want that piece kept as in the anchor.
- budget_inr: a new total budget, ONLY if they stated a figure. "cheaper" with no figure sets cheaper=true instead.
  "spend more" with no figure sets pricier=true.
- note: any other wish in their words (for example "more formal").
Never invent a colour or a number the shopper did not say.
