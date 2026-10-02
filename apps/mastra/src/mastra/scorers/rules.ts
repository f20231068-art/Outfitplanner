/**
 * The scoring rules, as plain functions: a finished session in, a score between 0 and 1 (and a reason out).
 * They are deterministic and free, so they can score every run. Mastra wrappers live in ./index.ts.
 *
 * What these measure is the PIPELINE'S guarantees (budget, verification, men's clothing, no duplicates),
 * not taste. Judging whether an outfit looks good needs a model or a person; see the notes in README.
 */

import type { Outfit, SessionCase, SessionResult } from '../stylist/session'

export interface Verdict {
  score: number // 0 (bad) .. 1 (good)
  reason: string
}

const clamp = (n: number) => Math.max(0, Math.min(1, n))
const pct = (n: number) => `${Math.round(n * 100)}%`
const items = (outfits: Outfit[]) => outfits.flatMap((o) => [o.top, o.bottom])

/** Wanted: exactly `expected` outfits. */
export function outfitCount(r: SessionResult, c: Partial<SessionCase>, expected = c.expect?.outfits ?? 4): Verdict {
  if (r.outcome === 'error') return { score: 0, reason: `the session failed: ${r.error ?? 'unknown error'}` }
  const n = r.outfits.length
  return { score: clamp(n / expected), reason: `${n} of ${expected} outfits delivered` }
}

/** Every outfit must cost no more than the shopper's budget. */
export function withinBudget(r: SessionResult, c: Partial<SessionCase>): Verdict {
  const budget = c.expect?.budget
  if (budget === undefined) return { score: 1, reason: 'no budget to check for this case' }
  if (r.outfits.length === 0) return { score: 0, reason: 'no outfits to check against the budget' }
  const over = r.outfits.filter((o) => o.total_inr > budget)
  return {
    score: clamp(1 - over.length / r.outfits.length),
    reason: over.length ? `${over.length} outfit(s) over the ₹${budget} budget (max ₹${Math.max(...over.map((o) => o.total_inr))})` : `all ${r.outfits.length} within ₹${budget}`,
  }
}

/** Every product shown carries a passing verification report. */
export function allItemsVerified(r: SessionResult): Verdict {
  const all = items(r.outfits)
  if (all.length === 0) return { score: 0, reason: 'no products to check' }
  const ok = all.filter((i) => i.verification?.is_match === true).length
  return { score: ok / all.length, reason: `${ok} of ${all.length} products carry a passing verification` }
}

/** Informational: how many outfits have colours confirmed by the store (not just assumed from the search). */
export function confirmedColourShare(r: SessionResult): Verdict {
  if (r.outfits.length === 0) return { score: 0, reason: 'no outfits' }
  const high = r.outfits.filter((o) => o.confidence === 'high').length
  return { score: high / r.outfits.length, reason: `${high} of ${r.outfits.length} outfits have a store-confirmed colour (${pct(high / r.outfits.length)})` }
}

const NOT_MENS = /\b(women|womens|woman|ladies|lady|girl|girls|kid|kids|boy|boys|baby|infant|junior)\b/i

/** No women's or kids' items, by title and by the verifier's own gender check. */
export function menswearOnly(r: SessionResult): Verdict {
  const all = items(r.outfits)
  if (all.length === 0) return { score: 0, reason: 'no products to check' }
  const bad = all.filter(
    (i) => NOT_MENS.test(i.title) || i.verification?.checks?.some((c) => c.attribute === 'gender' && c.status === 'mismatch'),
  )
  return { score: 1 - bad.length / all.length, reason: bad.length ? `${bad.length} item(s) look like women's or kids' clothing, e.g. "${bad[0].title.slice(0, 50)}"` : 'every item is men\'s or unisex' }
}

/** The same product must not appear twice. */
export function noDuplicateProducts(r: SessionResult): Verdict {
  const ids = items(r.outfits).map((i) => i.product_id ?? i.url)
  if (ids.length === 0) return { score: 0, reason: 'no products to check' }
  const unique = new Set(ids).size
  return { score: unique / ids.length, reason: unique === ids.length ? 'every product appears once' : `${ids.length - unique} repeated product(s)` }
}

const GARMENTS = ['t-shirt', 'tshirt', 'tee', 'polo', 'henley', 'hoodie', 'sweatshirt', 'sweater', 'shirt', 'jacket', 'kurta',
  'jeans', 'chinos', 'chino', 'joggers', 'jogger', 'cargo', 'trousers', 'pants', 'shorts', 'track']
export const garmentOf = (title: string): string => GARMENTS.find((g) => title.toLowerCase().includes(g)) ?? 'other'

/** Outfits should differ in garment type, not just colour. */
export function garmentVariety(r: SessionResult): Verdict {
  if (r.outfits.length < 2) return { score: r.outfits.length === 1 ? 1 : 0, reason: 'fewer than two outfits' }
  const pairs = new Set(r.outfits.map((o) => `${garmentOf(o.top.title)}+${garmentOf(o.bottom.title)}`))
  return { score: pairs.size / r.outfits.length, reason: `${pairs.size} different top+bottom combinations in ${r.outfits.length} outfits` }
}

/** Arithmetic integrity: each outfit's total is exactly its two prices added. */
export function priceIntegrity(r: SessionResult): Verdict {
  if (r.outfits.length === 0) return { score: 0, reason: 'no outfits' }
  const wrong = r.outfits.filter((o) => o.total_inr !== o.top.price_inr + o.bottom.price_inr || o.top.price_inr <= 0 || o.bottom.price_inr <= 0)
  return { score: 1 - wrong.length / r.outfits.length, reason: wrong.length ? `${wrong.length} outfit(s) with a wrong total or a non-positive price` : 'all totals equal top + bottom' }
}

/** The agent asks exactly for what the shopper left out: no more, no less. */
export function askedOnlyWhatIsMissing(r: SessionResult, c: Partial<SessionCase>): Verdict {
  const want = new Set(c.expect?.asks ?? [])
  const got = new Set(r.asked)
  const union = new Set([...want, ...got])
  if (union.size === 0) return { score: 1, reason: 'nothing was missing and nothing was asked' }
  const both = [...union].filter((x) => want.has(x as never) && got.has(x))
  const missed = [...want].filter((x) => !got.has(x))
  const extra = [...got].filter((x) => !want.has(x as never))
  return {
    score: both.length / union.size,
    reason: [missed.length && `did not ask for: ${missed.join(', ')}`, extra.length && `asked unnecessarily: ${extra.join(', ')}`].filter(Boolean).join('; ') || `asked exactly for: ${[...got].join(', ')}`,
  }
}

/** The whole session finishes within a time budget; the score decays to 0 at three times the target. */
export function latency(r: SessionResult, _c: Partial<SessionCase>, targetMs = 60_000): Verdict {
  const t = r.totalMs
  const score = t <= targetMs ? 1 : clamp(1 - (t - targetMs) / (2 * targetMs))
  return { score, reason: `${(t / 1000).toFixed(1)}s against a ${(targetMs / 1000).toFixed(0)}s target` }
}

/** No errors, and no search failed along the way. */
export function noBackendErrors(r: SessionResult): Verdict {
  if (r.outcome === 'error' || r.error) return { score: 0, reason: `error: ${r.error ?? r.outcome}` }
  if (r.stats.search_errors > 0) return { score: 0.5, reason: `${r.stats.search_errors} search(es) failed` }
  return { score: 1, reason: 'no errors' }
}

/** Cost guard: a normal session needs about 6 model calls and 8 searches. Far more means a loop or waste. */
export function callEfficiency(r: SessionResult): Verdict {
  const llm = r.stats.llm_calls
  const searches = r.stats.searches
  const over = Math.max(0, llm - 8) + Math.max(0, searches - 16)
  return { score: clamp(1 - over / 10), reason: `${llm} model calls, ${searches} searches` }
}
