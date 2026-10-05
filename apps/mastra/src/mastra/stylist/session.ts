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
  expect?: { budget?: number; asks?: Array<'budget' | 'occasion'>; outfits?: number; wishes?: Wishes }
  /** Messages the shopper types AFTER the first outfits arrive ("cheaper", "more like outfit 2", a question). */
  followUps?: FollowUp[]
}

/**
 * What the shopper asked for in each piece. Every entry must appear in the product title; an entry may list alternatives
 * with "|" ("white|off white|ivory", "t-shirt|tee|tshirt") because stores name the same thing in different ways.
 */
export interface Wishes {
  top?: string[]
  bottom?: string[]
}

export interface FollowUp {
  say: string
  /** outfits: should this message produce a new set? budget: the most each new outfit may cost. */
  expect?: { outfits?: boolean; budget?: number }
}

/** What one follow-up message produced. */
export interface Round {
  said: string
  reply: string | null
  outfits: Outfit[]
  error: string | null
  outcome: string
  expect?: FollowUp['expect']
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
  /** One entry per follow-up message, in order (empty when the case has none). */
  rounds: Round[]
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
    asked: [], rounds: [], styleNames: [], turns: 0, totalMs: 0, stages: [],
    stats: { llm_calls: 0, searches: 0, search_errors: 0 }, traceIds: [], error: null,
  }
  try {
    result.conversationId = await api.createConversation()
    let text: string | null = c.prompt
    let styleId: string | undefined

    for (let turn = 1; turn <= MAX_TURNS && text !== null; turn++) {
      result.turns = turn
      const reply = await api.sendMessage(result.conversationId, text, {
        traceparent: hooks.traceparent?.(),
        onEvent: (e) => hooks.onEvent?.(turn, e),
        styleId,
      })
      if (reply.traceId) result.traceIds.push(reply.traceId)
      text = null
      styleId = undefined

      for (const { event, data } of reply.events) {
        if (event === 'status') {
          result.stages.push({ turn, stage: data.stage, label: data.label, durationMs: data.duration_ms ?? 0 })
        } else if (event === 'outfits') {
          result.outfits = data.outfits
        } else if (event === 'message') {
          result.assistantMessage = data.text
        } else if (event === 'error') {
          result.error = data.message
        } else if (event === 'pending' && data?.type === 'ask') {
          const field = fieldAsked(data.question)
          if (field) result.asked.push(field)
          const answer = field ? c.answers?.[field] : undefined
          text = answer ?? null // no scripted answer: the conversation stops here, which is itself a result
        } else if (event === 'pending' && data?.type === 'choose_style') {
          result.styleNames = data.styles.map((s: { name: string }) => s.name)
          const pick = c.style ?? 0
          const chosen = typeof pick === 'number'
            ? data.styles[pick]
            : data.styles.find((s: { id: string; name: string }) => [s.id, s.name.toLowerCase()].includes(String(pick).toLowerCase()))
          const card = chosen ?? data.styles[0]
          text = card.name // what the shopper "clicked", sent together with the card's id
          styleId = card.id
        } else if (event === 'done') {
          result.outcome = data.outcome === 'error' ? 'error' : data.outcome === 'no_outfits' ? 'no_outfits' : data.outcome === 'ok' ? 'ok' : 'incomplete'
          for (const k of ['llm_calls', 'searches', 'search_errors'] as const) result.stats[k] += data.stats?.[k] ?? 0
        }
      }
      if (result.error) break
    }

    // The conversation does not end: keep talking after the outfits arrive.
    for (const f of c.followUps ?? []) {
      if (result.error || !result.outfits.length) break
      const round: Round = { said: f.say, reply: null, outfits: [], error: null, outcome: 'incomplete', expect: f.expect }
      const reply = await api.sendMessage(result.conversationId, f.say, {
        traceparent: hooks.traceparent?.(),
        onEvent: (e) => hooks.onEvent?.(result.turns + 1, e),
      })
      result.turns += 1
      if (reply.traceId) result.traceIds.push(reply.traceId)
      for (const { event, data } of reply.events) {
        if (event === 'status') result.stages.push({ turn: result.turns, stage: data.stage, label: data.label, durationMs: data.duration_ms ?? 0 })
        else if (event === 'outfits') round.outfits = data.outfits
        else if (event === 'message') round.reply = data.text
        else if (event === 'error') round.error = data.message
        else if (event === 'done') {
          round.outcome = String(data.outcome)
          for (const k of ['llm_calls', 'searches', 'search_errors'] as const) result.stats[k] += data.stats?.[k] ?? 0
        }
      }
      result.rounds.push(round)
    }
  } catch (err) {
    result.outcome = 'error'
    result.error = err instanceof Error ? err.message : String(err)
  }
  result.totalMs = Math.round(performance.now() - started)
  return result
}
