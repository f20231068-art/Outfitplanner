import type { StreamEvent } from './types'

/**
 * Turns a streamed response body into events. The browser's built-in EventSource cannot POST or send
 * an Authorization header, so we read the stream ourselves.
 *
 * The wire format is blocks separated by a blank line:
 *     event: status
 *     data: {"stage": "..."}
 * A block can arrive split across network chunks, so we keep a buffer and only act on complete blocks.
 */
export function parseBlock(block: string): StreamEvent | null {
  let event = ''
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim()
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  if (!event || !data) return null
  try {
    return { event, data: JSON.parse(data) } as StreamEvent
  } catch {
    return null // a malformed block is skipped, never crashes the page
  }
}

export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<StreamEvent> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let end: number
      while ((end = buffer.indexOf('\n\n')) !== -1) {
        const parsed = parseBlock(buffer.slice(0, end))
        buffer = buffer.slice(end + 2)
        if (parsed) yield parsed
      }
    }
    const rest = parseBlock(buffer.trim())
    if (rest) yield rest
  } finally {
    reader.releaseLock()
  }
}
