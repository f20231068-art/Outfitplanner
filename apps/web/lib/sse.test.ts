import { describe, expect, it } from 'vitest'
import { parseBlock, readEvents } from './sse'

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
}

async function collect(body: ReadableStream<Uint8Array>) {
  const out = []
  for await (const ev of readEvents(body)) out.push(ev)
  return out
}

describe('parseBlock', () => {
  it('reads an event name and its JSON data', () => {
    expect(parseBlock('event: status\ndata: {"stage":"a","label":"Styles ready"}')).toEqual({
      event: 'status',
      data: { stage: 'a', label: 'Styles ready' },
    })
  })
  it('skips malformed blocks instead of throwing', () => {
    expect(parseBlock('event: status\ndata: {not json')).toBeNull()
    expect(parseBlock('data: {"a":1}')).toBeNull()
    expect(parseBlock('')).toBeNull()
  })
})

describe('readEvents', () => {
  it('yields each complete event in order', async () => {
    const events = await collect(streamOf('event: status\ndata: {"stage":"x","label":"One"}\n\nevent: done\ndata: {}\n\n'))
    expect(events.map((e) => e.event)).toEqual(['status', 'done'])
  })

  it('reassembles an event that arrives split across network chunks', async () => {
    const events = await collect(streamOf('event: mess', 'age\ndata: {"role":"assist', 'ant","text":"Hi"}\n', '\n'))
    expect(events).toEqual([{ event: 'message', data: { role: 'assistant', text: 'Hi' } }])
  })

  it('handles Windows line endings', async () => {
    const events = await collect(streamOf('event: done\r\ndata: {}\r\n\r\n'))
    expect(events.map((e) => e.event)).toEqual(['done'])
  })

  it('keeps unicode (the rupee sign) intact even when a character is split between chunks', async () => {
    const enc = new TextEncoder().encode('event: message\ndata: {"role":"assistant","text":"₹4000"}\n\n')
    const cut = enc.indexOf(0xe2) + 1 // inside the 3-byte ₹ character
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(enc.slice(0, cut))
        c.enqueue(enc.slice(cut))
        c.close()
      },
    })
    const events = await collect(body)
    expect(events[0]).toEqual({ event: 'message', data: { role: 'assistant', text: '₹4000' } })
  })

  it('does not lose a final event that has no trailing blank line', async () => {
    const events = await collect(streamOf('event: done\ndata: {}'))
    expect(events.map((e) => e.event)).toEqual(['done'])
  })

  it('ignores a corrupt block and still delivers the ones after it', async () => {
    const events = await collect(streamOf('event: status\ndata: {broken\n\nevent: done\ndata: {}\n\n'))
    expect(events.map((e) => e.event)).toEqual(['done'])
  })
})
