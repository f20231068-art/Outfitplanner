/**
 * A tamper-evident audit log kept in SQLite (libSQL).
 *
 * Each entry stores the hash of the entry before it:
 *
 *     hash = SHA-256( canonical JSON of { ts, kind, actor, action, details, prev } )
 *
 * Change or delete any entry and every hash after it stops matching; `verify()` finds the first
 * broken link. The table also refuses UPDATE and DELETE (database triggers). Someone with full control
 * of the database file could remove those triggers, but not without the chain breaking.
 *
 * `details` holds ids, names, durations and hashes of inputs/outputs. Never message text or secrets.
 */

import { createHash } from 'node:crypto'
import { createClient, type Client } from '@libsql/client'

export const GENESIS = '0'.repeat(64)

export interface AuditEntry {
  kind: string // 'span' | 'score' | ...
  actor: string // who or what acted: 'system', a user id, a scorer id
  action: string // what happened: 'workflow_run', 'tool_call', 'score'
  details: Record<string, unknown>
}

export interface StoredEntry extends AuditEntry {
  seq: number
  ts: string
  prev: string
  hash: string
}

export interface ChainReport {
  ok: boolean
  entries: number
  firstBadSeq?: number
  reason?: string
}

/** JSON with keys in a fixed order and no spaces: the same entry must always give the same bytes. */
export function canonicalize(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'null'
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`
  const obj = value as Record<string, unknown>
  const keys = Object.keys(obj)
    .filter((k) => obj[k] !== undefined)
    .sort()
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalize(obj[k])}`).join(',')}}`
}

export function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

export function entryHash(e: Pick<StoredEntry, 'ts' | 'kind' | 'actor' | 'action' | 'details' | 'prev'>): string {
  return sha256(canonicalize({ ts: e.ts, kind: e.kind, actor: e.actor, action: e.action, details: e.details, prev: e.prev }))
}

export class AuditLog {
  private readonly db: Client
  private ready: Promise<void>
  private tail: Promise<unknown> = Promise.resolve() // appends run one at a time so the chain cannot fork

  constructor(url: string) {
    this.db = createClient({ url })
    this.ready = this.init()
  }

  private async init(): Promise<void> {
    await this.db.batch(
      [
        `CREATE TABLE IF NOT EXISTS audit_chain (
           seq     INTEGER PRIMARY KEY AUTOINCREMENT,
           ts      TEXT NOT NULL,
           kind    TEXT NOT NULL,
           actor   TEXT NOT NULL,
           action  TEXT NOT NULL,
           details TEXT NOT NULL,
           prev    TEXT NOT NULL,
           hash    TEXT NOT NULL UNIQUE
         )`,
        `CREATE TRIGGER IF NOT EXISTS audit_chain_no_update BEFORE UPDATE ON audit_chain
           BEGIN SELECT RAISE(ABORT, 'audit_chain is append-only'); END`,
        `CREATE TRIGGER IF NOT EXISTS audit_chain_no_delete BEFORE DELETE ON audit_chain
           BEGIN SELECT RAISE(ABORT, 'audit_chain is append-only'); END`,
      ],
      'write',
    )
  }

  /** Add one entry. Safe to call from many places at once: calls are queued and chained in order. */
  append(entry: AuditEntry): Promise<StoredEntry> {
    const run = this.tail.then(() => this.appendNow(entry))
    this.tail = run.catch(() => undefined) // one failed append must not block the ones after it
    return run
  }

  private async appendNow(entry: AuditEntry): Promise<StoredEntry> {
    await this.ready
    const last = await this.db.execute('SELECT hash FROM audit_chain ORDER BY seq DESC LIMIT 1')
    const prev = (last.rows[0]?.hash as string | undefined) ?? GENESIS
    const ts = new Date().toISOString()
    const hash = entryHash({ ts, ...entry, prev })
    const res = await this.db.execute({
      sql: 'INSERT INTO audit_chain (ts, kind, actor, action, details, prev, hash) VALUES (?, ?, ?, ?, ?, ?, ?)',
      args: [ts, entry.kind, entry.actor, entry.action, canonicalize(entry.details), prev, hash],
    })
    return { ...entry, seq: Number(res.lastInsertRowid), ts, prev, hash }
  }

  async entries(limit = 100): Promise<StoredEntry[]> {
    await this.ready
    const res = await this.db.execute({ sql: 'SELECT * FROM audit_chain ORDER BY seq DESC LIMIT ?', args: [limit] })
    return res.rows
      .map((r) => ({
        seq: Number(r.seq),
        ts: String(r.ts),
        kind: String(r.kind),
        actor: String(r.actor),
        action: String(r.action),
        details: JSON.parse(String(r.details)) as Record<string, unknown>,
        prev: String(r.prev),
        hash: String(r.hash),
      }))
      .reverse()
  }

  /** Walk the whole log, recomputing every hash. */
  async verify(): Promise<ChainReport> {
    await this.ready
    const res = await this.db.execute('SELECT * FROM audit_chain ORDER BY seq')
    let prev = GENESIS
    let count = 0
    for (const r of res.rows) {
      count++
      const seq = Number(r.seq)
      if (String(r.prev) !== prev) {
        return { ok: false, entries: count, firstBadSeq: seq, reason: 'an entry before this one was removed or changed' }
      }
      const expected = entryHash({
        ts: String(r.ts),
        kind: String(r.kind),
        actor: String(r.actor),
        action: String(r.action),
        details: JSON.parse(String(r.details)),
        prev,
      })
      if (expected !== String(r.hash)) {
        return { ok: false, entries: count, firstBadSeq: seq, reason: "this entry's contents do not match its hash" }
      }
      prev = String(r.hash)
    }
    return { ok: true, entries: count }
  }

  /** For tests: what a database administrator could do. Not used by the app. */
  get rawClient(): Client {
    return this.db
  }

  close(): void {
    this.db.close()
  }
}
