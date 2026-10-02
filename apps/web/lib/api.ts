import { readEvents } from './sse'
import type { BuyLink, ConversationDetail, ConversationSummary, StreamEvent } from './types'

export const API = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/** A message that is safe to show the user. Anything else becomes a generic one. */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public retryAfter?: number,
  ) {
    super(message)
  }
}

// The short-lived access token lives only in memory: it is gone when the tab closes, and no script
// injected into the page can find it in storage. The long-lived refresh token is an HttpOnly cookie
// the page's JavaScript cannot read at all.
let accessToken: string | null = null
let refreshing: Promise<boolean> | null = null

export function hasSession(): boolean {
  return accessToken !== null
}

/** Ask for a new access token using the refresh cookie. Concurrent callers share one request, because
 *  each refresh replaces the cookie and a second simultaneous one would look like token theft. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const r = await fetch(`${API}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'X-Requested-With': 'stylist-web' },
      })
      if (!r.ok) {
        accessToken = null
        return false
      }
      accessToken = (await r.json()).access_token
      return true
    } catch {
      return false
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

async function message(r: Response): Promise<string> {
  try {
    const body = await r.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail) && body.detail[0]?.msg) return String(body.detail[0].msg).replace(/^Value error, /, '')
  } catch {
    /* not JSON */
  }
  return 'Something went wrong. Please try again.'
}

async function request(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers)
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  let r: Response
  try {
    r = await fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
  } catch {
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0)
  }
  if (r.status === 401 && retry && (await refreshSession())) return request(path, init, false)
  if (!r.ok) throw new ApiError(await message(r), r.status, Number(r.headers.get('retry-after')) || undefined)
  return r
}

async function authenticate(path: string, email: string, password: string): Promise<void> {
  const r = await request(`/auth${path}`, { method: 'POST', body: JSON.stringify({ email, password }) }, false)
  accessToken = (await r.json()).access_token
}

export const login = (email: string, password: string) => authenticate('/login', email, password)
export const register = (email: string, password: string) => authenticate('/register', email, password)

export async function logout(): Promise<void> {
  try {
    await request('/auth/logout', { method: 'POST', headers: { 'X-Requested-With': 'stylist-web' } }, false)
  } finally {
    accessToken = null
  }
}

export async function me(): Promise<{ id: string; email: string }> {
  return (await request('/auth/me')).json()
}

export async function createConversation(): Promise<{ id: string }> {
  return (await request('/conversations', { method: 'POST' })).json()
}

export async function listConversations(): Promise<ConversationSummary[]> {
  return (await request('/conversations')).json()
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return (await request(`/conversations/${id}`)).json()
}

export async function buyLink(productId: string): Promise<BuyLink> {
  return (await request(`/products/${encodeURIComponent(productId)}/buy-link`, { method: 'POST' })).json()
}

/** Send a message and receive the agent's progress as it happens. */
export async function* sendMessage(conversationId: string, text: string): AsyncGenerator<StreamEvent> {
  const r = await request(`/conversations/${conversationId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ text }),
  })
  if (!r.body) throw new ApiError('The server sent an empty reply.', r.status)
  yield* readEvents(r.body)
}
