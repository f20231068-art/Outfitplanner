import { describe, expect, it } from 'vitest'
import type { Outfit, SessionResult } from '../mastra/stylist/session'
import { cases } from './cases'
import { COLUMNS, gateFailures, scoreCase } from './report'

const item = (title: string, price: number, id: string) => ({
  product_id: id, title, retailer: 'Myntra', price_inr: price, url: `https://x/${id}`, image_url: 'i',
  verification: { is_match: true, confidence: 'high', checks: [{ attribute: 'gender', status: 'match' }] },
})
const outfit = (i: number, garment: string): Outfit => {
  const top = item(`Men's ${garment} T-Shirt`.replace('T-Shirt', ['polo', 'henley', 'hoodie', 't-shirt'][i]), 600, `t${i}`)
  const bottom = item(`Men's ${['jeans', 'chinos', 'joggers', 'cargo'][i]}`, 1400, `b${i}`)
  return { id: `o${i}`, total_inr: 2000, confidence: 'high', rationale: 'r', top, bottom }
}
const healthy = (): SessionResult => ({
  caseId: 'college-4000', conversationId: 'c', outcome: 'ok', outfits: [0, 1, 2, 3].map((i) => outfit(i, 'Olive')),
  assistantMessage: 'ok', asked: [], styleNames: [], turns: 2, totalMs: 9000, stages: [],
  stats: { llm_calls: 4, searches: 8, search_errors: 0 }, traceIds: [], error: null,
})
const college = cases.find((c) => c.id === 'college-4000')!
const rowFor = (result: SessionResult) => ({ id: 'college-4000', verdicts: scoreCase(result, college) })

describe('the pass/fail gate can really fail', () => {
  it('passes a healthy session', () => {
    expect(gateFailures([rowFor(healthy())])).toEqual([])
  })

  it('fails when an outfit goes over budget', () => {
    const r = healthy()
    r.outfits[2].top.price_inr = 2800 // 2800 + 1400 = 4200: consistent arithmetic, but over the 4000 budget
    r.outfits[2].total_inr = 4200
    const failures = gateFailures([rowFor(r)])
    expect(failures).toHaveLength(1)
    expect(failures[0]).toMatch(/budget.*over the ₹4000/)
  })

  it('fails when a women\'s item slips through', () => {
    const r = healthy()
    r.outfits[1].top.title = "Women's Floral Top"
    expect(gateFailures([rowFor(r)]).join()).toMatch(/menswear/)
  })

  it('fails when a product was never verified', () => {
    const r = healthy()
    r.outfits[0].bottom.verification = { is_match: false }
    expect(gateFailures([rowFor(r)]).join()).toMatch(/verified/)
  })

  it('fails when the same product is shown twice', () => {
    const r = healthy()
    r.outfits[3].top.product_id = 't0'
    expect(gateFailures([rowFor(r)]).join()).toMatch(/no dupes/)
  })

  it('fails when fewer than four outfits come back', () => {
    const r = healthy()
    r.outfits = r.outfits.slice(0, 2)
    expect(gateFailures([rowFor(r)]).join()).toMatch(/4 outfits/)
  })

  it('fails when the agent asked a question nobody needed', () => {
    const r = healthy()
    r.asked = ['budget'] // the shopper already gave one
    expect(gateFailures([rowFor(r)]).join()).toMatch(/asks right.*unnecessarily/)
  })

  it('fails on an error, with the reason', () => {
    const r: SessionResult = { ...healthy(), outcome: 'error', error: 'The assistant is busy', outfits: [] }
    const text = gateFailures([rowFor(r)]).join('\n')
    expect(text).toMatch(/no errors.*busy/)
  })

  it('does NOT fail the run for a soft quality signal, only reports it', () => {
    const r = healthy()
    r.totalMs = 500_000 // far too slow, but speed is informational
    r.outfits.forEach((o) => (o.confidence = 'low'))
    expect(gateFailures([rowFor(r)])).toEqual([])
    expect(scoreCase(r, college).latency.score).toBe(0)
    expect(scoreCase(r, college).colour.score).toBe(0)
  })
})

describe('the dataset itself', () => {
  it('has unique case ids and every case states what it expects', () => {
    const ids = cases.map((c) => c.id)
    expect(new Set(ids).size).toBe(ids.length)
    for (const c of cases) {
      expect(c.expect?.budget, c.id).toBeGreaterThan(0)
      expect(c.expect?.asks, c.id).toBeDefined()
    }
  })

  it('every case that expects a question provides an answer for it', () => {
    for (const c of cases) for (const field of c.expect?.asks ?? []) expect(c.answers?.[field], `${c.id} needs an answer for ${field}`).toBeTruthy()
  })

  it('covers complete, partial and empty requests', () => {
    const askCounts = new Set(cases.map((c) => c.expect?.asks?.length))
    expect([...askCounts].sort()).toEqual([0, 1, 2])
  })

  it('has a gate column for every hard guarantee and nothing soft is gated', () => {
    const gated = COLUMNS.filter((c) => c.gate).map((c) => c.key)
    expect(gated).toEqual(expect.arrayContaining(['budget', 'verified', 'men', 'dupes', 'price', 'asks', 'errors', 'count']))
    expect(gated).not.toContain('latency')
    expect(gated).not.toContain('colour')
  })
})
