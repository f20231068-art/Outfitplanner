/** What is actually in Mastra's database and in the audit chain?   npm run inspect -w apps/mastra */

import { createClient } from '@libsql/client'
import { AuditLog } from '../mastra/audit/chain'
import { config } from '../mastra/config'

const db = createClient({ url: config.mastraDbUrl })
const tables = (await db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")).rows.map((r) => String(r.name))
console.log('tables in mastra.db with rows:')
for (const t of tables) {
  const n = Number((await db.execute(`SELECT count(*) AS n FROM "${t}"`)).rows[0].n)
  if (n > 0) console.log(`  ${t.padEnd(32)} ${n}`)
}

if (tables.includes('mastra_scorers')) {
  const rows = (await db.execute('SELECT scorerId, score, entityType, source, traceId FROM mastra_scorers ORDER BY createdAt DESC LIMIT 14')).rows
  console.log('\nlatest stored scores:')
  for (const r of rows) console.log(`  ${String(r.scorerId).padEnd(24)} ${String(r.score).padEnd(5)} ${String(r.entityType ?? '').padEnd(10)} trace ${String(r.traceId ?? '').slice(0, 8)}`)
}
db.close()

const audit = new AuditLog(config.auditDbUrl)
const report = await audit.verify()
const entries = await audit.entries(40)
console.log(`\naudit chain: ${report.ok ? 'intact' : 'BROKEN'}, ${report.entries} entries; last entries:`)
for (const e of entries.slice(-12)) console.log(`  #${e.seq} ${e.kind}/${e.action.padEnd(16)} ${String(e.details.name ?? e.details.score ?? '').slice(0, 40)}`)
audit.close()
