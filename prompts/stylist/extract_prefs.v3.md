You read a conversation between a shopper and a fashion stylist for Indian men's clothing.
Extract ONLY what the shopper has actually said:
- budget_inr: total budget in INR.
- occasion: what the clothes are for.
- requests: any wishes the shopper expressed about the look or the garments, in their own words, kept short.
  Collect everything they asked for. Do not turn the occasion into a request, do not add anything the shopper
  did not say, and leave it null if they expressed no such wish.
- top and bottom: what the shopper asked for in EACH piece. A top is a t-shirt, shirt, polo, hoodie, sweatshirt, jacket,
  kurta and so on; a bottom is jeans, chinos, trousers, cargos, joggers, shorts and so on. For each piece set only what
  they said:
    item   the garment name alone ("t-shirt", "jeans", "chinos")
    color  a colour they named for THAT piece ("white", "navy")
    fit    the fit ("oversized", "baggy", "slim", "relaxed")
    fabric the material ("denim", "linen", "cotton")
  Leave a piece null if they said nothing about it, and leave a field null if they did not state it. Never guess.
- avoid: colours they do not want ("no black" -> ["black"]), else null.

Read the way a person would:
- A colour belongs to the garment it is written next to. "white oversized tshirt and denim baggy jeans" means the top is a
  white oversized t-shirt and the bottom is baggy denim jeans: top {item "t-shirt", color "white", fit "oversized"},
  bottom {item "jeans", fit "baggy", fabric "denim"}. "Denim" is a fabric, not a colour.
- "white baggy jeans": the bottom is white baggy jeans; say nothing about the top.
- "navy chinos with a white shirt": bottom {chinos, navy}, top {shirt, white}.
- Words like "oversized", "baggy" and "slim" are fits, not part of the garment name.
- Style words ("streetwear", "formal", "old money") go in requests, not in top or bottom.
- If the shopper asked for a kind of outfit as a whole ("a suit"), put it in requests and leave top and bottom null.

If the shopper changed their mind, the LATEST statement wins.
If something has not been stated, leave it null. Never guess.
Convert amounts like "4k" or "under 4000 rupees" to an integer number of INR.
