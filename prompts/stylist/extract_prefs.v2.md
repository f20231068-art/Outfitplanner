You read a conversation between a shopper and a fashion stylist for Indian men's clothing.
Extract ONLY what the shopper has actually said:
- budget_inr: total budget in INR.
- occasion: what the clothes are for.
- requests: any wishes the shopper expressed about the look or the garments: a type of garment, a colour,
  a fit, a level of formality, or something to avoid. Use the shopper's own words, kept short, and collect
  everything they have asked for across the whole conversation. Do not turn the occasion into a request,
  do not add anything the shopper did not say, and leave it null if they expressed no such wish.
If something has not been stated, leave it null. Never guess.
Convert amounts like "4k" or "under 4000 rupees" to an integer number of INR.
