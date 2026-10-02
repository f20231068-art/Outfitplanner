/** A small client for the Python API, used by the Mastra workflow to drive real shopper sessions. */

import { readAll, type ApiEvent } from './sse'

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message)
  }
}

export interface TurnResponse {
  events: ApiEvent[]
  /** The trace id the API says it used (it adopts ours when we send a valid `traceparent`). */
  traceId: string | null
  elapsedMs: number
}

export class StylistApi {
  private token: string | null = null

  constructor(
    public readonly baseUrl: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  /** How long to wait before retrying after a 429, in ms (the server says how long). Replaceable in tests. */
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms))

  private async call(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers)
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`)
    if (init.body) headers.set('Content-Type', 'application/json')
    let res = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers })
    // Rate-limited: a well-behaved client waits as long as the server asks, then tries again. The request was
    // refused BEFORE it was processed, so repeating it cannot double anything.
    for (let attempt = 0; attempt < 3 && res.status === 429; attempt++) {
      const wait = Math.min(Number(res.headers.get('retry-after')) || 5, 65)
      await this.sleep(wait * 1000 + 250)
      res = await this.fetchImpl(`${this.baseUrl}${path}`, { ...init, headers })
    }
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const body = (await res.json()) as { detail?: unknown }
        if (typeof body.detail === 'string') detail = body.detail
      } catch {
        /* not JSON */
      }
      throw new ApiError(detail, res.status)
    }
    return res
  }

  /** Log in, creating the evaluation account the first time. */
  async ensureUser(email: string, password: string): Promise<void> {
    const body = JSON.stringify({ email, password })
    try {
      this.token = ((await (await this.call('/auth/login', { method: 'POST', body })).json()) as { access_token: string }).access_token
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 401) throw err
      this.token = ((await (await this.call('/auth/register', { method: 'POST', body })).json()) as { access_token: string }).access_token
    }
  }

  async createConversation(): Promise<string> {
    return ((await (await this.call('/conversations', { method: 'POST' })).json()) as { id: string }).id
  }

  /** Send one message and read the whole streamed answer. */
  async sendMessage(
    conversationId: string,
    text: string,
    opts: { traceparent?: string; onEvent?: (e: ApiEvent) => void } = {},
  ): Promise<TurnResponse> {
    const started = performance.now()
    const res = await this.call(`/conversations/${conversationId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ text }),
      headers: opts.traceparent ? { traceparent: opts.traceparent } : undefined,
    })
    if (!res.body) throw new ApiError('empty response', res.status)
    const events = await readAll(res.body, opts.onEvent)
    return { events, traceId: res.headers.get('x-trace-id'), elapsedMs: Math.round(performance.now() - started) }
  }
}
