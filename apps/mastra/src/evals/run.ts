/**
 * Offline evaluation: play every case through the traced workflow and score the results.
 *
 *   npm run eval -w apps/mastra                      (all cases)
 *   npm run eval -w apps/mastra -- --only college-4000,missing-budget
 *   npm run eval -w apps/mastra -- --concurrency 3
 *
 * Needs the API running (BACKEND_MODE=demo is free and instant; live uses real model credits).
 * Each run is also scored by Mastra itself (the scorers attached to the workflow step), so the scores
 * appear in Studio and in the audit chain. The table printed here uses the same rules.
 * Exit code 1 if any hard guarantee ("gate") fails, so this can run in CI.
 */

import { flushAndClose, mastra } from '../mastra'
import type { Verdict } from '../mastra/scorers/rules'
import type { SessionResult } from '../mastra/stylist/session'
import { cases } from './cases'
import { COLUMNS, gateFailures, scoreCase } from './report'

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`)
  return i >= 0 ? process.argv[i + 1] : undefined
}

async function runCase(c: (typeof cases)[number]): Promise<{ result: SessionResult; traceId?: string }> {
  const run = await mastra.getWorkflow('stylistSession').createRun()
  const res = await run.start({ inputData: c })
  if (res.status !== 'success') {
    const raw = res.status === 'failed' ? (res as { error?: unknown }).error : undefined
    const error = raw instanceof Error ? raw.message : raw ? JSON.stringify(raw) : `workflow ${res.status}`
    return { result: { caseId: c.id, conversationId: null, outcome: 'error', outfits: [], assistantMessage: null, asked: [], rounds: [], styleNames: [], turns: 0, totalMs: 0, stages: [], stats: { llm_calls: 0, searches: 0, search_errors: 0 }, traceIds: [], error }, traceId: res.traceId }
  }
  return { result: res.result as unknown as SessionResult, traceId: res.traceId }
}

async function main() {
  const only = arg('only')?.split(',')
  const selected = only ? cases.filter((c) => only.includes(c.id)) : cases
  const concurrency = Number(arg('concurrency') ?? 2)
  console.log(`Running ${selected.length} case(s), ${concurrency} at a time, against the API in config.\n`)

  const rows: Array<{ id: string; traceId?: string; verdicts: Record<string, Verdict>; result: SessionResult }> = []
  const queue = [...selected]
  await Promise.all(
    Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
      for (let c = queue.shift(); c; c = queue.shift()) {
        const { result, traceId } = await runCase(c)
        const verdicts = scoreCase(result, c)
        rows.push({ id: c.id, traceId, verdicts, result })
        console.log(`  done ${c.id.padEnd(18)} ${result.outcome.padEnd(10)} ${(result.totalMs / 1000).toFixed(1)}s  trace ${traceId?.slice(0, 8) ?? '-'}`)
      }
    }),
  )
  rows.sort((a, b) => selected.findIndex((c) => c.id === a.id) - selected.findIndex((c) => c.id === b.id))

  // ---- the report ---------------------------------------------------------------------------------------
  const pad = (s: string, n: number) => s.padEnd(n).slice(0, n)
  console.log('\n' + pad('case', 18) + COLUMNS.map((c) => pad(c.label, 11)).join(''))
  for (const r of rows) {
    console.log(pad(r.id, 18) + COLUMNS.map((c) => pad(r.verdicts[c.key].score.toFixed(2), 11)).join(''))
  }
  const avg = (key: string) => rows.reduce((a, r) => a + r.verdicts[key].score, 0) / (rows.length || 1)
  console.log(pad('AVERAGE', 18) + COLUMNS.map((c) => pad(avg(c.key).toFixed(2), 11)).join(''))

  const failures = gateFailures(rows)
  console.log(failures.length ? `\nGATES FAILED (${failures.length}):\n  ` + failures.join('\n  ') : '\nAll hard guarantees held for every case.')
  console.log('\nTraces and scores: open Studio (npm run studio) -> Observability. Audit chain: npm run audit:verify')

  await flushAndClose() // write out buffered traces and scores before exiting
  process.exit(failures.length ? 1 : 0)
}

main().catch((err) => {
  console.error(err)
  process.exit(2)
})
