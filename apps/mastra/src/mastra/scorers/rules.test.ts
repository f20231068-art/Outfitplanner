import { describe, expect, it } from 'vitest'
import type { Item, Outfit, SessionResult } from '../stylist/session'
import {
  allItemsVerified, askedOnlyWhatIsMissing, callEfficiency, confirmedColourShare, garmentOf, garmentVariety, latency,
  menswearOnly, noBackendErrors, noDuplicateProducts, outfitCount, priceIntegrity, withinBudget,
} from './rules'

const item = (title: string, price: number, id: string, ok = true): Item => ({
  product_id: id, title, retailer: 'Myntra', price_inr: price, url: `https://x/${id}`, image_url: 'https://i',
  verification: { is_match: ok, confidence: 'high', checks: [{ attribute: 'gender', status: 'match' }] },
})
const outfit = (top: Item, bottom: Item, confidence: 'high' | 'low' = 'high'): Outfit => ({
  id: top.product_id + bottom.product_id!, total_inr: top.price_inr + bottom.price_inr, confidence, rationale: 'r', top, bottom,
})
const good = (): Outfit[] => [
  outfit(item("Men's White T-Shirt", 600, 'a'), item("Men's Black Jeans", 1400, 'b')),
  outfit(item("Men's Navy Polo", 700, 'c'), item("Men's Beige Chinos", 1300, 'd')),
  outfit(item("Men's Olive Henley", 650, 'e'), item("Men's Grey Joggers", 1100, 'f')),
  outfit(item("Men's Sky Shirt", 800, 'g'), item("Men's Navy Trousers", 1200, 'h'), 'low'),
]
const result = (over: Partial<SessionResult> = {}): SessionResult => ({
  caseId: 'c1', conversationId: 'x', outcome: 'ok', outfits: good(), assistantMessage: 'hi', asked: [], styleNames: [],
  turns: 2, totalMs: 20_000, stages: [], stats: { llm_calls: 4, searches: 8, search_errors: 0 }, traceIds: [], error: null, ...over,
})

describe('outfitCount', () => {
  it('is 1 with four outfits and falls in proportion', () => {
    expect(outfitCount(result(), {}).score).toBe(1)
    expect(outfitCount(result({ outfits: good().slice(0, 3) }), {}).score).toBe(0.75)
    expect(outfitCount(result({ outfits: [] }), {}).score).toBe(0)
  })
  it('is 0 when the session itself failed, and says why', () => {
    const v = outfitCount(result({ outcome: 'error', error: 'busy', outfits: good() }), {})
    expect(v.score).toBe(0)
    expect(v.reason).toContain('busy')
  })
  it('never exceeds 1 even if there are more outfits than expected', () => {
    expect(outfitCount(result({ outfits: [...good(), ...good()] }), {}).score).toBe(1)
  })
})

describe('withinBudget', () => {
  it('passes when every outfit is at or under the budget', () => {
    expect(withinBudget(result(), { expect: { budget: 4000 } }).score).toBe(1)
    expect(withinBudget(result(), { expect: { budget: 2000 } }).score).toBe(1) // exactly 2000 is allowed
  })
  it('fails in proportion to the outfits over budget and names the worst', () => {
    const v = withinBudget(result(), { expect: { budget: 1900 } })
    expect(v.score).toBe(0.25)
    expect(v.reason).toContain('₹2000')
  })
  it('is not applicable without a budget, and fails with no outfits', () => {
    expect(withinBudget(result(), {}).score).toBe(1)
    expect(withinBudget(result({ outfits: [] }), { expect: { budget: 4000 } }).score).toBe(0)
  })
})

describe('verification, menswear, duplicates, arithmetic', () => {
  it('counts products without a passing verification', () => {
    const outfits = good()
    outfits[0].top = item('x', 600, 'a', false)
    expect(allItemsVerified(result({ outfits })).score).toBe(7 / 8)
  })
  it('catches women\'s and kids\' items by title', () => {
    const outfits = good()
    outfits[1].bottom = item("Women's Beige Chinos", 1300, 'd')
    outfits[2].top = item('Boys Olive Henley', 650, 'e')
    const v = menswearOnly(result({ outfits }))
    expect(v.score).toBe(6 / 8)
    expect(v.reason).toContain('Women')
  })
  it('catches a gender mismatch the verifier recorded even when the title is silent', () => {
    const outfits = good()
    outfits[0].top.verification = { is_match: false, checks: [{ attribute: 'gender', status: 'mismatch' }] }
    expect(menswearOnly(result({ outfits })).score).toBe(7 / 8)
  })
  it('flags a product shown twice', () => {
    const outfits = good()
    outfits[3].bottom = item("Men's Black Jeans", 1400, 'b')
    expect(noDuplicateProducts(result({ outfits })).score).toBe(7 / 8)
  })
  it('flags wrong totals and non-positive prices', () => {
    const outfits = good()
    outfits[0].total_inr = 1
    outfits[1].top.price_inr = 0
    expect(priceIntegrity(result({ outfits })).score).toBe(0.5)
  })
})

describe('variety', () => {
  it('reads the garment from the title', () => {
    expect(garmentOf("Men's Olive Henley Neck T-Shirt")).toBe('t-shirt')
    expect(garmentOf('Cotton Polo')).toBe('polo')
    expect(garmentOf('Mystery Item')).toBe('other')
  })
  it('rewards different combinations and punishes the same garments in other colours', () => {
    expect(garmentVariety(result()).score).toBe(1)
    const same = [1, 2, 3, 4].map((n) => outfit(item(`Men's C${n} T-Shirt`, 600, `t${n}`), item(`Men's C${n} Jeans`, 1400, `j${n}`)))
    expect(garmentVariety(result({ outfits: same })).score).toBe(0.25)
  })
})

describe('conversation and cost', () => {
  it('scores what the agent asked against what was actually missing', () => {
    const c = { expect: { asks: ['budget'] as Array<'budget' | 'occasion'> } }
    expect(askedOnlyWhatIsMissing(result({ asked: ['budget'] }), c).score).toBe(1)
    expect(askedOnlyWhatIsMissing(result({ asked: [] }), c).score).toBe(0)
    const extra = askedOnlyWhatIsMissing(result({ asked: ['budget', 'occasion'] }), c)
    expect(extra.score).toBe(0.5)
    expect(extra.reason).toContain('unnecessarily')
    expect(askedOnlyWhatIsMissing(result({ asked: [] }), {}).score).toBe(1)
  })
  it('latency is 1 up to the target and decays to 0 at three times it', () => {
    expect(latency(result({ totalMs: 59_000 }), {}).score).toBe(1)
    expect(latency(result({ totalMs: 120_000 }), {}).score).toBe(0.5)
    expect(latency(result({ totalMs: 400_000 }), {}).score).toBe(0)
  })
  it('errors and failed searches lower the score', () => {
    expect(noBackendErrors(result()).score).toBe(1)
    expect(noBackendErrors(result({ stats: { llm_calls: 1, searches: 1, search_errors: 2 } })).score).toBe(0.5)
    expect(noBackendErrors(result({ outcome: 'error', error: 'x' })).score).toBe(0)
  })
  it('flags runaway call counts', () => {
    expect(callEfficiency(result()).score).toBe(1)
    expect(callEfficiency(result({ stats: { llm_calls: 30, searches: 8, search_errors: 0 } })).score).toBe(0)
  })
  it('reports the share of store-confirmed colours', () => {
    expect(confirmedColourShare(result()).score).toBe(0.75)
  })
})
