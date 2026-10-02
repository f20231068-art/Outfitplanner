import { describe, expect, it } from 'vitest'
import { ApiError, StylistApi, type TurnResponse } from './client'
import { runSession, type SessionCase } from './session'
import { readAll, type ApiEvent } from './sse'

const STYLES = [
  { id: 'streetwear', name: 'Streetwear', description: 'd', image_prompt: 'p' },
  { id: 'smart-casual', name: 'Smart Casual', description: 'd', image_prompt: 'p' },
  { id: 'minimalist', name: 'Minimalist', description: 'd', image_prompt: 'p' },
]
const done = (outcome: string, stats = { llm_calls: 1, searches: 0, search_errors: 0 }): ApiEvent => ({ event: 'done', data: { outcome, stats, trace_id: 't' } })
const status = (stage: string, ms: number): ApiEvent => ({ event: 'status', data: { stage, label: stage, duration_ms: ms, elapsed_ms: ms } })
const askBudget: ApiEvent = { event: 'interrupt', data: { type: 'ask', question: "What's your total budget for the outfit, in rupees?", missing: ['budget_inr'] } }
const askOccasion: ApiEvent = { event: 'interrupt', data: { type: 'ask', question: "What's the occasion?", missing: ['occasion'] } }
const chooseStyle: ApiEvent = { event: 'interrupt', data: { type: 'choose_style', styles: STYLES } }
const outfits: ApiEvent = { event: 'outfits', data: { outfits: [{ id: 'o1', total_inr: 2000, confidence: 'high', rationale: 'r', top: {}, bottom: {} }] } }

/** A stand-in API that plays back one scripted reply per message and remembers what it was sent. */
function fakeApi(script: ApiEvent[][]) {
  const sent: string[] = []
  const traceparents: Array<string | undefined> = []
  const api = {
    createConversation: async () => 'conv-1',
    sendMessage: async (_id: string, text: string, opts: { traceparent?: string; onEvent?: (e: ApiEvent) => void } = {}): Promise<TurnResponse> => {
      sent.push(text)
      traceparents.push(opts.traceparent)
      const events = script[sent.length - 1] ?? [done('ok')]
      events.forEach((e) => opts.onEvent?.(e))
      return { events, traceId: `trace-${sent.length}`, elapsedMs: 5 }
    },
  } as unknown as StylistApi
  return { api, sent, traceparents }
}

const base: SessionCase = { id: 'c', prompt: 'college under 4000' }

describe('runSession: following the conversation', () => {
  it('goes straight to style choice, picks by position, and collects the outfits', async () => {
    const { api, sent } = fakeApi([[status('gather_prefs', 20), chooseStyle, done('waiting_for_user')], [status('plan_outfits', 30), outfits, { event: 'message', data: { text: 'Here you go' } }, done('ok', { llm_calls: 1, searches: 8, search_errors: 0 })]])
    const r = await runSession(api, { ...base, style: 1 })
    expect(sent).toEqual(['college under 4000', 'smart-casual'])
    expect(r.outcome).toBe('ok')
    expect(r.outfits).toHaveLength(1)
    expect(r.styleNames).toEqual(['Streetwear', 'Smart Casual', 'Minimalist'])
    expect(r.assistantMessage).toBe('Here you go')
    expect(r.stats).toEqual({ llm_calls: 2, searches: 8, search_errors: 0 }) // summed over both turns
    expect(r.traceIds).toEqual(['trace-1', 'trace-2'])
    expect(r.stages.map((s) => [s.turn, s.stage, s.durationMs])).toEqual([[1, 'gather_prefs', 20], [2, 'plan_outfits', 30]])
  })

  it.each([
    [{ style: 'minimalist' }, 'minimalist'],
    [{ style: 'Smart Casual' }, 'smart-casual'], // by display name, any case
    [{ style: 'no-such-style' }, 'streetwear'], // unknown: falls back to the first
    [{}, 'streetwear'],
  ])('picks the style for %j', async (extra, expected) => {
    const { api, sent } = fakeApi([[chooseStyle, done('waiting_for_user')], [outfits, done('ok')]])
    await runSession(api, { ...base, ...extra })
    expect(sent[1]).toBe(expected)
  })

  it('answers the agent\'s questions from the case and records what was asked, in order', async () => {
    const { api, sent } = fakeApi([[askBudget, done('waiting_for_user')], [askOccasion, done('waiting_for_user')], [chooseStyle, done('waiting_for_user')], [outfits, done('ok')]])
    const r = await runSession(api, { ...base, answers: { budget: 'around 3000', occasion: 'college' } })
    expect(sent).toEqual(['college under 4000', 'around 3000', 'college', 'streetwear'])
    expect(r.asked).toEqual(['budget', 'occasion'])
    expect(r.outcome).toBe('ok')
  })

  it('stops, and says so, when asked something the case has no answer for', async () => {
    const { api, sent } = fakeApi([[askBudget, done('waiting_for_user')]])
    const r = await runSession(api, base)
    expect(sent).toHaveLength(1)
    expect(r.asked).toEqual(['budget'])
    expect(r.outcome).toBe('incomplete')
  })

  it('never loops forever if the agent keeps asking', async () => {
    const loop = Array.from({ length: 20 }, () => [askBudget, done('waiting_for_user')])
    const { api, sent } = fakeApi(loop)
    const r = await runSession(api, { ...base, answers: { budget: 'x' } })
    expect(sent.length).toBe(6)
    expect(r.turns).toBe(6)
  })

  it('stops at an error event and keeps the message', async () => {
    const { api, sent } = fakeApi([[{ event: 'error', data: { message: 'The assistant is busy right now.' } }, done('error')]])
    const r = await runSession(api, base)
    expect(sent).toHaveLength(1)
    expect(r.outcome).toBe('error')
    expect(r.error).toBe('The assistant is busy right now.')
  })

  it('turns a thrown failure into an error result instead of crashing the evaluation', async () => {
    const api = { createConversation: async () => 'c', sendMessage: async () => { throw new ApiError('Cannot reach the server', 0) } } as unknown as StylistApi
    const r = await runSession(api, base)
    expect(r.outcome).toBe('error')
    expect(r.error).toBe('Cannot reach the server')
  })

  it('maps the API\'s outcomes', async () => {
    for (const [apiOutcome, expected] of [['no_outfits', 'no_outfits'], ['ok', 'ok'], ['waiting_for_user', 'incomplete'], ['weird', 'incomplete']] as const) {
      const { api } = fakeApi([[done(apiOutcome)]])
      expect((await runSession(api, base)).outcome).toBe(expected)
    }
  })
})

describe('runSession: tracing hooks', () => {
  it('asks for a fresh traceparent for every request and reports every event live', async () => {
    const { api, traceparents } = fakeApi([[chooseStyle, done('waiting_for_user')], [outfits, done('ok')]])
    const seen: Array<[number, string]> = []
    let n = 0
    await runSession(api, base, { traceparent: () => `00-${'a'.repeat(32)}-${String(++n).padStart(16, '0')}-01`, onEvent: (turn, e) => seen.push([turn, e.event]) })
    expect(traceparents).toHaveLength(2)
    expect(new Set(traceparents).size).toBe(2) // a different parent span id each time, the same trace id
    expect(traceparents.every((t) => t!.includes('a'.repeat(32)))).toBe(true)
    expect(seen.map(([t]) => t)).toEqual([1, 1, 2, 2])
  })

  it('works with no hooks at all', async () => {
    const { api, traceparents } = fakeApi([[done('ok')]])
    await runSession(api, base)
    expect(traceparents).toEqual([undefined])
  })
})

// ---- the HTTP client ---------------------------------------------------------------------------------
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json', ...headers } })

describe('StylistApi', () => {
  it('logs in, and creates the account the first time', async () => {
    const calls: string[] = []
    const api = new StylistApi('http://api', async (url) => {
      calls.push(String(url).replace('http://api', ''))
      return String(url).endsWith('/auth/login') ? json({ detail: 'Invalid email or password.' }, 401) : json({ access_token: 'tok' }, 201)
    })
    await api.ensureUser('a@b.com', 'long passphrase here')
    expect(calls).toEqual(['/auth/login', '/auth/register'])
  })

  it('does not hide a real failure behind a registration attempt', async () => {
    const api = new StylistApi('http://api', async () => json({ detail: 'down' }, 503))
    await expect(api.ensureUser('a@b.com', 'x')).rejects.toMatchObject({ status: 503 })
  })

  it('waits as long as the server says after a 429, then succeeds', async () => {
    let tries = 0
    const waits: number[] = []
    const api = new StylistApi('http://api', async () => (++tries < 3 ? json({ detail: 'slow down' }, 429, { 'retry-after': '7' }) : json({ id: 'c1' })))
    api.sleep = async (ms) => void waits.push(ms)
    expect(await api.createConversation()).toBe('c1')
    expect(tries).toBe(3)
    expect(waits).toEqual([7250, 7250])
  })

  it('gives up after three retries and reports the server\'s message', async () => {
    const api = new StylistApi('http://api', async () => json({ detail: 'Too many requests' }, 429, { 'retry-after': '1' }))
    api.sleep = async () => {}
    await expect(api.createConversation()).rejects.toMatchObject({ status: 429, message: 'Too many requests' })
  })

  it('caps an absurd retry-after so a hostile server cannot stall us for an hour', async () => {
    const waits: number[] = []
    const api = new StylistApi('http://api', async () => json({ detail: 'x' }, 429, { 'retry-after': '3600' }))
    api.sleep = async (ms) => void waits.push(ms)
    await api.createConversation().catch(() => {})
    expect(Math.max(...waits)).toBeLessThanOrEqual(65_250)
  })

  it('sends the traceparent header and reads the streamed answer and the trace id', async () => {
    let sentHeaders: Headers | undefined
    const body = 'event: status\ndata: {"stage":"x","label":"x","duration_ms":3}\n\nevent: done\ndata: {"outcome":"ok","stats":{}}\n\n'
    const api = new StylistApi('http://api', async (_u, init) => {
      sentHeaders = new Headers(init?.headers)
      return new Response(body, { status: 200, headers: { 'x-trace-id': 'abc123' } })
    })
    const r = await api.sendMessage('c', 'hello', { traceparent: '00-' + 'b'.repeat(32) + '-' + 'c'.repeat(16) + '-01' })
    expect(sentHeaders?.get('traceparent')).toContain('b'.repeat(32))
    expect(r.traceId).toBe('abc123')
    expect(r.events.map((e) => e.event)).toEqual(['status', 'done'])
  })
})

describe('readAll', () => {
  it('delivers each event as it arrives, even when one is split across chunks', async () => {
    const enc = new TextEncoder()
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.encode('event: status\ndata: {"a":'))
        c.enqueue(enc.encode('1}\n\nevent: done\ndata: {}\n\n'))
        c.close()
      },
    })
    const live: string[] = []
    const all = await readAll(stream, (e) => live.push(e.event))
    expect(live).toEqual(['status', 'done'])
    expect(all).toHaveLength(2)
  })
})
