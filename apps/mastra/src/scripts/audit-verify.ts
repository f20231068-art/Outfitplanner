/**
 * Verify the tamper-evident audit chain:   npm run audit:verify -w apps/mastra
 * Exit code 0 = intact, 1 = tampering or corruption found.
 */

import { AuditLog } from '../mastra/audit/chain'
import { config } from '../mastra/config'

const log = new AuditLog(config.auditDbUrl)
const report = await log.verify()
const recent = await log.entries(200)

const counts = new Map<string, number>()
for (const e of recent) counts.set(`${e.kind}/${e.action}`, (counts.get(`${e.kind}/${e.action}`) ?? 0) + 1)

console.log(`audit chain: ${report.ok ? 'INTACT' : 'BROKEN'} | ${report.entries} entries`)
if (!report.ok) console.log(`first bad entry: #${report.firstBadSeq}: ${report.reason}`)
if (counts.size) console.log('recent entries by kind:', Object.fromEntries(counts))
log.close()
process.exit(report.ok ? 0 : 1)
