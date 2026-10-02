/**
 * Plugs the tamper-evident audit chain into Mastra's tracing. Every finished span of an audited kind,
 * and every eval score, becomes one chained entry.
 *
 * What is recorded: ids, names, kinds, outcome, duration, and SHA-256 fingerprints of the input and
 * output. What is NOT recorded: the input/output themselves, error messages, or anything from prompts
 * and replies. A fingerprint lets you later prove "this exact input was processed" without storing it.
 */

import { SpanType, TracingEventType } from '@mastra/core/observability'
import type { ScoreEvent, TracingEvent } from '@mastra/core/observability'
import { BaseExporter } from '@mastra/observability'
import { AuditLog, canonicalize, sha256 } from './chain'

/** Span kinds worth an audit entry. Model chunks, steps and other fine-grained spans are skipped. */
export const AUDITED_SPAN_TYPES = new Set<string>([
  SpanType.WORKFLOW_RUN,
  SpanType.WORKFLOW_STEP,
  SpanType.AGENT_RUN,
  SpanType.TOOL_CALL,
  SpanType.MCP_TOOL_CALL,
  SpanType.MODEL_GENERATION,
  SpanType.SCORER_RUN,
])

const fingerprint = (value: unknown): string | null =>
  value === undefined || value === null ? null : sha256(canonicalize(value)).slice(0, 32)

export class AuditExporter extends BaseExporter {
  name = 'hash-chain-audit'

  constructor(private readonly log: AuditLog) {
    super()
  }

  protected async _exportTracingEvent(event: TracingEvent): Promise<void> {
    if (event.type !== TracingEventType.SPAN_ENDED) return
    const span = event.exportedSpan
    // A custom span can opt in by carrying `metadata.audit = true`
    const optedIn = (span.metadata as Record<string, unknown> | undefined)?.audit === true
    if (span.isInternal || !(AUDITED_SPAN_TYPES.has(span.type) || optedIn)) return

    try {
      await this.log.append({
        kind: 'span',
        actor: span.entityName ?? span.entityId ?? 'system',
        action: String(span.type),
        details: {
          name: span.name,
          traceId: span.traceId,
          spanId: span.id,
          parentSpanId: span.parentSpanId ?? null,
          isRoot: span.isRootSpan,
          outcome: span.errorInfo ? 'error' : 'ok',
          // the error's kind only, never its message (messages can quote user input)
          errorId: (span.errorInfo as { id?: string } | undefined)?.id ?? null,
          durationMs: span.endTime ? span.endTime.getTime() - span.startTime.getTime() : null,
          inputFingerprint: fingerprint(span.input),
          outputFingerprint: fingerprint(span.output),
        },
      })
    } catch (err) {
      // an audit failure must never break the traced request, but it must not be silent either
      this.logger.error('audit append failed', { error: err instanceof Error ? err.message : String(err) })
    }
  }

  /** Eval scores are part of the record: "this run was judged 0.5 by scorer X". */
  async onScoreEvent(event: ScoreEvent): Promise<void> {
    const s = event.score
    try {
      await this.log.append({
        kind: 'score',
        actor: s.scorerId,
        action: 'score',
        details: {
          scoreId: s.scoreId,
          score: s.score,
          traceId: s.traceId ?? null,
          spanId: s.spanId ?? null,
          experimentId: s.experimentId ?? null,
          source: s.source ?? null,
        },
      })
    } catch (err) {
      this.logger.error('audit append failed', { error: err instanceof Error ? err.message : String(err) })
    }
  }
}
