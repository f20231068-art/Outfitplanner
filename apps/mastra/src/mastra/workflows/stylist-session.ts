/**
 * The workflow that plays one shopper session against the API and is traced end to end.
 *
 *   Mastra workflow run  ->  step "converse"  ->  one child span per backend stage
 *                                                  (understood request, styles, outfits designed,
 *                                                   stores searched, items checked ...)
 *
 * The API adopts our trace id (W3C `traceparent` header), so its logs and audit-log entries carry the
 * same id as this trace. Every scorer is attached to the step, so each run is scored as it finishes.
 */

import type { MastraScorers } from '@mastra/core/evals'
import { SpanType } from '@mastra/core/observability'
import { createStep, createWorkflow } from '@mastra/core/workflows'
import { z } from 'zod'
import { config } from '../config'
import { allScorers } from '../scorers'
import { StylistApi } from '../stylist/client'
import { runSession, type SessionResult } from '../stylist/session'

export const caseSchema = z.object({
  id: z.string(),
  prompt: z.string(),
  answers: z.object({ budget: z.string().optional(), occasion: z.string().optional() }).optional(),
  style: z.union([z.number(), z.string()]).optional(),
  expect: z
    .object({
      budget: z.number().optional(),
      asks: z.array(z.enum(['budget', 'occasion'])).optional(),
      outfits: z.number().optional(),
    })
    .optional(),
})

const resultSchema = z.record(z.string(), z.any()) // a SessionResult: see stylist/session.ts

const hex16 = () => Array.from({ length: 16 }, () => Math.floor(Math.random() * 16).toString(16)).join('')

const clients = new Map<number, Promise<StylistApi>>()

/** A signed-in client for this case. Cases are spread over a small pool of evaluation accounts, so the API's
 *  per-user limits stay switched on and are never what an evaluation is measuring. */
function api(caseId: string): Promise<StylistApi> {
  const slot = [...caseId].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7) % Math.max(1, config.evalUsers)
  let client = clients.get(slot)
  if (!client) {
    const created = new StylistApi(config.apiUrl)
    client = created.ensureUser(config.evalEmail(slot), config.evalPassword).then(() => created)
    client.catch(() => clients.delete(slot)) // a failed sign-in is retried next time
    clients.set(slot, client)
  }
  return client
}

// every scorer judges every run (they are deterministic and free). Typed explicitly: it keeps TypeScript
// from mistaking this step for one of Mastra's other createStep forms.
const stepScorers: MastraScorers = Object.fromEntries(
  Object.entries(allScorers).map(([key, scorer]) => [key, { scorer, sampling: { type: 'ratio' as const, rate: 1 } }]),
)

export const converseStep = createStep({
  id: 'converse',
  description: 'Play the shopper side of a conversation and collect the outfits.',
  inputSchema: caseSchema,
  outputSchema: resultSchema,
  scorers: stepScorers,
  execute: async ({ inputData, tracingContext }) => {
    const client = await api(inputData.id)
    const parent = tracingContext?.currentSpan
    const traceId = parent?.traceId

    const result: SessionResult = await runSession(client, inputData, {
      // each request carries OUR trace id, so the API joins this trace
      traceparent: () => (traceId ? `00-${traceId}-${hex16()}-01` : undefined),
      onEvent: (turn, ev) => {
        if (ev.event !== 'status' || !parent) return
        // The API reports each stage when it FINISHES, with how long it took. Create the span now, backdated
        // by that duration, so the trace shows the stage's real length.
        const span = parent.createChildSpan({
          type: SpanType.GENERIC,
          name: `backend: ${ev.data.stage}`,
          entityName: `backend: ${ev.data.stage}`, // trace UIs build the span's display name from this
          startTime: new Date(Date.now() - (ev.data.duration_ms ?? 0)),
          // custom data goes in `metadata`: a generic span's `attributes` only accept Mastra's own fields
          metadata: { stage: ev.data.stage, label: ev.data.label, turn, durationMs: ev.data.duration_ms },
        })
        span?.end({ metadata: { elapsedMs: ev.data.elapsed_ms } })
      },
    })

    parent?.update({
      metadata: {
        caseId: result.caseId, outcome: result.outcome, outfits: result.outfits.length, turns: result.turns,
        llmCalls: result.stats.llm_calls, searches: result.stats.searches, apiTraceIds: result.traceIds,
      },
    })
    return result as unknown as Record<string, unknown>
  },
})

export const stylistSession = createWorkflow({
  id: 'stylist-session',
  inputSchema: caseSchema,
  outputSchema: resultSchema,
})
  .then(converseStep)
  .commit()
