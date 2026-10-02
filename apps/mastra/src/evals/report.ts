/** The report's columns and the pass/fail rule, kept separate from the runner so they can be tested. */

import * as rules from '../mastra/scorers/rules'
import type { SessionCase, SessionResult } from '../mastra/stylist/session'

type Rule = (r: SessionResult, c: SessionCase) => rules.Verdict

/** `gate` = a hard guarantee that must be 1.0 for every case; the rest are informational quality signals. */
export const COLUMNS: Array<{ key: string; label: string; rule: Rule; gate: boolean }> = [
  { key: 'count', label: '4 outfits', rule: rules.outfitCount, gate: true },
  { key: 'budget', label: 'budget', rule: rules.withinBudget, gate: true },
  { key: 'verified', label: 'verified', rule: rules.allItemsVerified, gate: true },
  { key: 'men', label: 'menswear', rule: rules.menswearOnly, gate: true },
  { key: 'dupes', label: 'no dupes', rule: rules.noDuplicateProducts, gate: true },
  { key: 'price', label: 'prices', rule: rules.priceIntegrity, gate: true },
  { key: 'asks', label: 'asks right', rule: rules.askedOnlyWhatIsMissing, gate: true },
  { key: 'errors', label: 'no errors', rule: rules.noBackendErrors, gate: true },
  { key: 'variety', label: 'variety', rule: rules.garmentVariety, gate: false },
  { key: 'colour', label: 'colour ok', rule: rules.confirmedColourShare, gate: false },
  { key: 'latency', label: 'speed', rule: (r, c) => rules.latency(r, c), gate: false },
  { key: 'calls', label: 'calls', rule: rules.callEfficiency, gate: false },
]

export interface Row {
  id: string
  verdicts: Record<string, rules.Verdict>
}

export function scoreCase(result: SessionResult, c: SessionCase): Record<string, rules.Verdict> {
  return Object.fromEntries(COLUMNS.map((col) => [col.key, col.rule(result, c)]))
}

/** Every hard guarantee that failed, as readable lines. Empty means the run passed. */
export function gateFailures(rows: Row[]): string[] {
  return rows.flatMap((r) =>
    COLUMNS.filter((c) => c.gate && r.verdicts[c.key].score < 1).map((c) => `${r.id} / ${c.label}: ${r.verdicts[c.key].reason}`),
  )
}
