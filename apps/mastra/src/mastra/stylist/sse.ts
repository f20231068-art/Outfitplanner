/** Reads the API's server-sent-event stream. Blocks are separated by a blank line; one can arrive in pieces. */

export interface ApiEvent {
  event: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any
}

export function parseBlock(block: string): ApiEvent | null {
  let event = ''
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!event || !data) return null
  try {
    return { event, data: JSON.parse(data) }
  } catch {
    return null
  }
}

/** Read the whole stream. `onEvent` is called the moment each event arrives, so callers can react live. */
export async function readAll(body: ReadableStream<Uint8Array>, onEvent?: (e: ApiEvent) => void): Promise<ApiEvent[]> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  const events: ApiEvent[] = []
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true }).split('\r\n').join('\n')
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const parsed = parseBlock(buffer.slice(0, end))
      buffer = buffer.slice(end + 2)
      if (parsed) {
        events.push(parsed)
        onEvent?.(parsed)
      }
    }
  }
  const rest = parseBlock(buffer.trim())
  if (rest) {
    events.push(rest)
    onEvent?.(rest)
  }
  return events
}
