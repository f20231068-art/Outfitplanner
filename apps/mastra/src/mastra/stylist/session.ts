/**
 * Plays a whole shopper session against the API: ask, answer the agent's questions, pick a style,
 * receive outfits. Returns everything the scorers need to judge it.
 */

import type { StylistApi } from './client'
import type { ApiEvent } from './sse'

export interface SessionCase {
  id: string
  prompt: string
  /** What the "shopper" says if the agent asks for it. If a needed answer is missing the session stops there. */
  answers?: { budget?: string; occasion?: string }
  /** Which style to pick: a position (0-based) or a name/id. Default: the first. */
  style?: number | string
  /** Ground truth for scorers: what SHOULD happen. */
  expect?: { budget?: number; asks?: Array<'budget' | 'occasion'>; outfits?: number }
}

export interface Item {
  product_id: string | null
  title: string
  retailer: string
  price_inr: number
  url: string
  image_url: string
  verification?: { is_match?: boolean; confidence?: string; checks?: Array<{ attribute: string; status: string }> } | null
}

export interface Outfit {
  id: string
  total_inr: number
  confidence: 'high' | 'low'
  rationale: string
  top: Item
  bottom: Item
}

export interface StageRecord {
  turn: number
  stage: string
  label: string
  durationMs: number
}

export interface SessionResult {
  caseId: string
  conversationId: string | null
  outcome: 'ok' | 'no_outfits' | 'error' | 'incomplete'
  outfits: Outfit[]
  assistantMessage: string | null
  /** Fields the agent asked about, in order, e.g. ['budget']. */
  asked: string[]
  styleNames: string[]
  turns: number
  totalMs: number
  stages: StageRecord[]
  stats: { llm_calls: number; searches: number; search_errors: number }
  traceIds: string[]
  error: string | null
}

export interface SessionHooks {
  /** A fresh W3C `traceparent` for the next request, so the API joins our trace. */
  traceparent?: () => string | undefined
  /** Called live for every event of every turn. */
  onEvent?: (turn: number, event: ApiEvent) => void
}

const MAX_TURNS = 6

function fieldAsked(question: string): 'budget' | 'occasion' | null {
  const q = question.toLowerCase()
  if (q.includes('budget')) return 'budget'
  if (q.includes('occasion')) return 'occasion'
  return null
}

export async function runSession(api: StylistApi, c: SessionCase, hooks: SessionHooks = {}): Promise<SessionResult> {
  const started = performance.now()
  const result: SessionResult = {
    caseId: c.id, conversationId: null, outcome: 'incomplete', outfits: [], assistantMessage: null,
    asked: [], styleNames: [], turns: 0, totalMs: 0, stages: [],
    stats: { llm_calls: 0, searches: 0, search_errors: 0 }, traceIds: [], error: null,
  }
  try {
    result.conversationId = await api.createConversation()
    let text: string | null = c.prompt

    for (let turn = 1; turn <= MAX_TURNS && text !== null; turn++) {
      result.turns = turn
      const reply = await api.sendMessage(result.conversationId, text, {
        traceparent: hooks.traceparent?.(),
        onEvent: (e) => hooks.onEvent?.(turn, e),
      })
      if (reply.traceId) result.traceIds.push(reply.traceId)
      text = null

      for (const { event, data } of reply.events) {
        if (event === 'status') {
          result.stages.push({ turn, stage: data.stage, label: data.label, durationMs: data.duration_ms ?? 0 })
        } else if (event === 'outfits') {
          result.outfits = data.outfits
        } else if (event === 'message') {
          result.assistantMessage = data.text
        } else if (event === 'error') {
          result.error = data.message
        } else if (event === 'interrupt' && data.type === 'ask') {
          const field = fieldAsked(data.question)
          if (field) result.asked.push(field)
          const answer = field ? c.answers?.[field] : undefined
          text = answer ?? null // no scripted answer: the conversation stops here, which is itself a result
        } else if (event === 'interrupt' && data.type === 'choose_style') {
          result.styleNames = data.styles.map((s: { name: string }) => s.name)
          const pick = c.style ?? 0
          const chosen = typeof pick === 'number'
            ? data.styles[pick]
            : data.styles.find((s: { id: string; name: string }) => [s.id, s.name.toLowerCase()].includes(String(pick).toLowerCase()))
          text = (chosen ?? data.styles[0]).id
        } else if (event === 'done') {
          result.outcome = data.outcome === 'error' ? 'error' : data.outcome === 'no_outfits' ? 'no_outfits' : data.outcome === 'ok' ? 'ok' : 'incomplete'
          for (const k of ['llm_calls', 'searches', 'search_errors'] as const) result.stats[k] += data.stats?.[k] ?? 0
        }
      }
      if (result.error) break
    }
  } catch (err) {
    result.outcome = 'error'
    result.error = err instanceof Error ? err.message : String(err)
  }
  result.totalMs = Math.round(performance.now() - started)
  return result
}
