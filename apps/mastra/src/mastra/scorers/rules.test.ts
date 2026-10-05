import { describe, expect, it } from 'vitest'
import type { Item, Outfit, SessionResult } from '../stylist/session'
import {
  allItemsVerified, askedOnlyWhatIsMissing, callEfficiency, followUpsHandled, garmentOf, garmentVariety, latency,
  menswearOnly, noBackendErrors, noDuplicateProducts, outfitCount, priceIntegrity, rationaleHidesColours, shopperWishesHonoured, withinBudget,
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
  turns: 2, totalMs: 20_000, stages: [], rounds: [], stats: { llm_calls: 4, searches: 8, search_errors: 0 }, traceIds: [], error: null, ...over,
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
})

describe('followUpsHandled', () => {
  const round = (over = {}) => ({ said: 'cheaper', reply: 'ok', outfits: [outfit(item("Men's Cyan Polo", 500, 'n1'), item("Men's Tan Chinos", 800, 'n2'))], error: null, outcome: 'ok', expect: { outfits: true, budget: 1500 }, ...over })

  it('has nothing to judge when the case has no follow-ups', () => {
    expect(followUpsHandled(result()).score).toBe(1)
  })
  it('passes when a change request delivers new, in-budget, unseen outfits', () => {
    expect(followUpsHandled(result({ rounds: [round()] })).score).toBe(1)
  })
  it('fails a follow-up with an error, no reply, no outfits when expected, or a search when not expected', () => {
    for (const bad of [{ error: 'boom' }, { reply: null }, { outfits: [] }, { expect: { outfits: false } }]) {
      expect(followUpsHandled(result({ rounds: [round(bad)] })).score, JSON.stringify(bad)).toBe(0)
    }
  })
  it('fails outfits over the new budget', () => {
    const v = followUpsHandled(result({ rounds: [round({ expect: { outfits: true, budget: 1000 } })] }))
    expect(v.score).toBe(0)
    expect(v.reason).toMatch(/over the new budget of \u20b91000/)
  })
  it('fails a product the shopper has already seen, whether in the first set or an earlier follow-up', () => {
    const seenAgain = round({ outfits: [outfit(item("Men's Navy Polo", 700, 'c'), item("Men's Cyan Chinos", 800, 'zz'))] }) // 'c' was in the first set
    expect(followUpsHandled(result({ rounds: [seenAgain] })).reason).toMatch(/already shown/)
    expect(followUpsHandled(result({ rounds: [round(), round()] })).score).toBe(0.5) // the second repeats the first follow-up
  })
})

describe('rationaleHidesColours', () => {
  it('passes explanations about garments and flags ones that spell out a colour', () => {
    expect(rationaleHidesColours(result()).score).toBe(1)
    const leaking = good().map((o, i) => (i === 0 ? { ...o, rationale: 'Olive henley with navy trousers' } : o))
    const v = rationaleHidesColours(result({ outfits: leaking }))
    expect(v.score).toBe(0.75)
    expect(v.reason).toMatch(/mention a colour/)
  })
})

describe('shopperWishesHonoured', () => {
  const wishes = { top: ['white|ivory', 't-shirt|tee'], bottom: ['jeans|denim'] }
  const asked = (outfits: Outfit[]) => shopperWishesHonoured(result({ outfits }), { expect: { wishes } })
  const ok = () => [
    outfit(item("Men's White Oversized T-Shirt", 600, 'a'), item("Men's Baggy Denim Jeans", 1400, 'b')),
    outfit(item('Ivory Boxy Tee', 700, 'c'), item('Wide Leg Jeans', 1300, 'd')),
  ]

  it('is 1 when every product in the described pieces names what was asked, alternatives included', () => {
    expect(asked(ok()).score).toBe(1)
  })
  it('falls in proportion and names the first misses', () => {
    const bad = [...ok(), outfit(item('Blue Oversized T-Shirt', 650, 'e'), item('Black Joggers', 1100, 'f'))]
    const v = asked(bad)
    expect(v.score).toBeCloseTo(1 - 2 / 9) // 3 outfits x 3 details; the blue tee lacks white|ivory, the joggers lack jeans|denim
    expect(v.reason).toContain('outfit 3 top')
  })
  it('does not apply when the shopper described nothing, and fails with no outfits', () => {
    expect(shopperWishesHonoured(result(), { expect: {} }).score).toBe(1)
    expect(shopperWishesHonoured(result(), { expect: { wishes: { top: [] } } }).score).toBe(1)
    expect(asked([]).score).toBe(0)
  })
  it('checks only the piece the shopper described', () => {
    const onlyBottom = shopperWishesHonoured(result({ outfits: ok() }), { expect: { wishes: { bottom: ['denim'] } } })
    expect(onlyBottom.score).toBe(0.5) // the second outfit says "Wide Leg Jeans", not denim
  })
})
