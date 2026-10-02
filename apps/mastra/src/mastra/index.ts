import { Mastra } from '@mastra/core'
import { LibSQLStore } from '@mastra/libsql'
import { MastraStorageExporter, Observability } from '@mastra/observability'
import { OtelExporter } from '@mastra/otel-exporter'
import { AuditLog } from './audit/chain'
import { AuditExporter } from './audit/exporter'
import { config } from './config'
import { allScorers } from './scorers'
import { stylistSession } from './workflows/stylist-session'

/** The tamper-evident record of what ran and how it scored. Verify it any time with `npm run audit:verify`. */
export const auditLog = new AuditLog(config.auditDbUrl)

const exporters = [
  new MastraStorageExporter(), // traces and scores, browsable in Studio
  new AuditExporter(auditLog), // the hash-chained audit trail
  // optional: also send traces to a local OpenTelemetry backend such as Jaeger
  ...(config.otlpEndpoint
    ? [new OtelExporter({ provider: { custom: { endpoint: config.otlpEndpoint, protocol: 'http/protobuf' as const, headers: {} } } })]
    : []),
]

/** Call before a script exits: write out buffered traces and scores FIRST, then close the databases.
 *  (Closing storage first loses the last events, which is what a plain `mastra.shutdown()` does.) */
export async function flushAndClose(): Promise<void> {
  await mastra.observability.flush()
  await mastra.shutdown()
  auditLog.close()
}

export const mastra = new Mastra({
  storage: new LibSQLStore({ id: 'mastra-storage', url: config.mastraDbUrl }),
  observability: new Observability({
    configs: {
      default: { serviceName: config.serviceName, exporters },
    },
  }),
  scorers: allScorers,
  workflows: { stylistSession },
})
