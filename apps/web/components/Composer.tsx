'use client'

import { FormEvent, KeyboardEvent, useEffect, useRef } from 'react'
import { SendIcon } from './icons'

const MAX = 500

/** The pill input. Enter sends, Shift+Enter adds a line; the box grows to a few lines and focus returns after a send. */
export default function Composer({
  draft,
  setDraft,
  onSend,
  busy,
  placeholder,
}: {
  draft: string
  setDraft: (v: string) => void
  onSend: (text: string) => void
  busy: boolean
  placeholder: string
}) {
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    const el = box.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 132)}px`
  }, [draft])

  useEffect(() => {
    if (!busy) box.current?.focus()
  }, [busy])

  function submit(e: FormEvent) {
    e.preventDefault()
    onSend(draft)
  }
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      onSend(draft)
    }
  }

  const near = draft.length > MAX * 0.8
  return (
    <div className="composer">
      <div className="composer-inner">
        <form onSubmit={submit}>
          <textarea
            ref={box}
            rows={1}
            value={draft}
            maxLength={MAX}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            placeholder={placeholder}
            aria-label="Your message"
            disabled={busy}
          />
          <button className="send" type="submit" disabled={busy || !draft.trim()} aria-label="Send">
            <SendIcon />
          </button>
        </form>
        <div className="hintline">
          <span>Enter to send · Shift+Enter for a new line</span>
          {near && <span className={draft.length >= MAX ? 'over' : ''}>{draft.length}/{MAX}</span>}
        </div>
      </div>
    </div>
  )
}
