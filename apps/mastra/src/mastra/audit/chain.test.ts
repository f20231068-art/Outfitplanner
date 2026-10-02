import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { AuditLog, GENESIS, canonicalize, entryHash } from './chain'

let log: AuditLog

beforeEach(() => {
  log = new AuditLog(':memory:')
})
afterEach(() => {
  log.close()
})

const entry = (n: number) => ({ kind: 'span', actor: 'system', action: 'tool_call', details: { n } })

describe('canonicalize', () => {
  it('gives the same text whatever order the keys were written in', () => {
    expect(canonicalize({ b: 1, a: { d: 2, c: 3 } })).toBe(canonicalize({ a: { c: 3, d: 2 }, b: 1 }))
  })
  it('drops undefined and keeps nested arrays in order', () => {
    expect(canonicalize({ a: undefined, b: [3, 1, { z: 1, y: 2 }] })).toBe('{"b":[3,1,{"y":2,"z":1}]}')
  })
})

describe('the chain', () => {
  it('links every entry to the one before and verifies', async () => {
    const a = await log.append(entry(1))
    const b = await log.append(entry(2))
    expect(a.prev).toBe(GENESIS)
    expect(b.prev).toBe(a.hash)
    expect(await log.verify()).toEqual({ ok: true, entries: 2 })
  })

  it('the hash can be recomputed from the stored entry', async () => {
    const a = await log.append(entry(7))
    expect(entryHash(a)).toBe(a.hash)
  })

  it('an empty log is valid', async () => {
    expect(await log.verify()).toEqual({ ok: true, entries: 0 })
  })

  it('stays one unbroken chain when many things append at once', async () => {
    await Promise.all(Array.from({ length: 40 }, (_, i) => log.append(entry(i))))
    expect(await log.verify()).toEqual({ ok: true, entries: 40 })
  })

  it('keeps going after one append fails', async () => {
    const bad = log.append({ kind: 'x', actor: 'a', action: 'b', details: { n: 1n as unknown as number } }) // BigInt cannot be JSON
    await expect(bad).rejects.toThrow()
    await log.append(entry(2))
    expect(await log.verify()).toEqual({ ok: true, entries: 1 })
  })
})

describe('tampering', () => {
  it('the database refuses to update or delete an entry', async () => {
    await log.append(entry(1))
    await expect(log.rawClient.execute("UPDATE audit_chain SET actor = 'evil'")).rejects.toThrow(/append-only/)
    await expect(log.rawClient.execute('DELETE FROM audit_chain')).rejects.toThrow(/append-only/)
    expect((await log.verify()).ok).toBe(true)
  })

  async function asAdministrator(sql: string, args: unknown[] = []) {
    // someone with full control of the database file switches the protections off, edits, switches them on
    await log.rawClient.execute('DROP TRIGGER audit_chain_no_update')
    await log.rawClient.execute('DROP TRIGGER audit_chain_no_delete')
    await log.rawClient.execute({ sql, args: args as never })
  }

  it('detects an edited entry', async () => {
    for (let i = 1; i <= 4; i++) await log.append(entry(i))
    await asAdministrator(`UPDATE audit_chain SET details = '{"n":999}' WHERE seq = 3`)
    const report = await log.verify()
    expect(report).toMatchObject({ ok: false, firstBadSeq: 3 })
    expect(report.reason).toMatch(/contents/)
  })

  it('detects a deleted entry', async () => {
    for (let i = 1; i <= 4; i++) await log.append(entry(i))
    await asAdministrator('DELETE FROM audit_chain WHERE seq = 2')
    const report = await log.verify()
    expect(report).toMatchObject({ ok: false, firstBadSeq: 3 })
    expect(report.reason).toMatch(/removed/)
  })

  it('detects a cleverer forgery: an entry rewritten together with its own hash', async () => {
    for (let i = 1; i <= 4; i++) await log.append(entry(i))
    const victim = (await log.entries(10)).find((e) => e.seq === 2)!
    const forged = entryHash({ ...victim, details: { n: 777 } })
    await asAdministrator('UPDATE audit_chain SET details = ?, hash = ? WHERE seq = 2', ['{"n":777}', forged])
    expect(await log.verify()).toMatchObject({ ok: false, firstBadSeq: 3 }) // the NEXT entry still points at the old hash
  })

  it('detects the last entry being replaced', async () => {
    for (let i = 1; i <= 3; i++) await log.append(entry(i))
    await asAdministrator(`UPDATE audit_chain SET action = 'nothing_happened' WHERE seq = 3`)
    expect(await log.verify()).toMatchObject({ ok: false, firstBadSeq: 3 })
  })
})

describe('persistence', () => {
  it('the chain survives a restart: reopening the file continues the same chain', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'audit-'))
    const url = pathToFileURL(join(dir, 'audit.db')).href
    const first = new AuditLog(url)
    const last = await first.append(entry(1))
    first.close()

    const second = new AuditLog(url) // a new process would do exactly this
    const next = await second.append(entry(2))
    expect(next.prev).toBe(last.hash)
    expect(await second.verify()).toEqual({ ok: true, entries: 2 })
    second.close()
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      /* Windows may still hold the file for a moment; a temp folder left behind is harmless */
    }
  })
})
