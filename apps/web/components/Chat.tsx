'use client'

import { useRouter } from 'next/navigation'
import { FormEvent, KeyboardEvent, useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, createConversation, getConversation, listConversations, logout, me, refreshSession, sendMessage } from '../lib/api'
import type { ChatMessage, ConversationSummary, Outfit, Pending } from '../lib/types'
import OutfitCard from './OutfitCard'
import StyleCards from './StyleCards'

const MAX = 500
const EXAMPLES = ['College wear, around ₹4000', 'Smart casual for office, under ₹6000', 'Party look, ₹5000']

export default function Chat() {
  const router = useRouter()
  const [email, setEmail] = useState<string | null>(null)
  const [convos, setConvos] = useState<ConversationSummary[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState<Pending | null>(null)
  const [outfits, setOutfits] = useState<Outfit[]>([])
  const [steps, setSteps] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  const loadList = useCallback(() => listConversations().then(setConvos).catch(() => {}), [])

  // on first load: restore the session from the refresh cookie, or send the visitor to log in
  useEffect(() => {
    ;(async () => {
      if (!(await refreshSession())) return router.replace('/login')
      try {
        setEmail((await me()).email)
        await loadList()
      } catch {
        router.replace('/login')
      }
    })()
  }, [router, loadList])

  // A block body on purpose: an effect must return nothing (or a cleanup function), and in newer
  // browsers scrollIntoView() returns a Promise, which React would try to call as a cleanup.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, pending, outfits, steps])

  function reset() {
    setActiveId(null)
    setMessages([])
    setPending(null)
    setOutfits([])
    setSteps([])
    setError(null)
  }

  async function open(id: string) {
    if (busy) return
    reset()
    try {
      const c = await getConversation(id)
      setActiveId(c.id)
      setMessages(c.messages)
      setPending(c.pending)
      setOutfits(c.outfits)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not open that conversation.')
    }
  }

  async function ask(text: string, shownAs?: string) {
    const clean = text.trim()
    if (!clean || busy) return
    setError(null)
    setBusy(true)
    setSteps([])
    setPending(null)
    setDraft('')
    try {
      let id = activeId
      if (!id) {
        id = (await createConversation()).id
        setActiveId(id)
      }
      setMessages((m) => [...m, { role: 'user', text: shownAs ?? clean }])
      for await (const ev of sendMessage(id, clean)) {
        if (ev.event === 'status') setSteps((s) => [...s, ev.data.label])
        else if (ev.event === 'interrupt') setPending(ev.data)
        else if (ev.event === 'outfits') setOutfits((o) => [...o, ...ev.data.outfits])
        else if (ev.event === 'message') setMessages((m) => [...m, ev.data])
        else if (ev.event === 'error') setError(ev.data.message)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setBusy(false)
      setSteps([])
      loadList()
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    ask(draft)
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask(draft)
    }
  }

  async function signOut() {
    await logout().catch(() => {})
    router.replace('/login')
  }

  if (email === null) return <div className="auth" aria-busy="true"><div className="skeleton" style={{ width: 280 }} /></div>

  const empty = messages.length === 0 && !pending && !busy

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">AI Stylist</span>
        <div className="who">
          <span>{email}</span>
          <button className="btn secondary small" onClick={signOut}>
            Log out
          </button>
        </div>
      </header>

      <nav className="sidebar" aria-label="Your conversations">
        <button className="btn small" onClick={reset} disabled={busy}>
          + New look
        </button>
        {convos.map((c) => (
          <button key={c.id} className="convo" aria-current={c.id === activeId} onClick={() => open(c.id)} title={c.title}>
            {c.title}
          </button>
        ))}
      </nav>

      <div className="main">
        <div className="thread">
          <div className="thread-inner">
            {empty && (
              <div className="welcome">
                <h2>What are you shopping for?</h2>
                <p>Tell me the occasion and your budget in rupees. I will suggest styles, then find outfits at Myntra, Amazon, Flipkart and more.</p>
                <div className="chips">
                  {EXAMPLES.map((x) => (
                    <button key={x} className="chip" onClick={() => ask(x)}>
                      {x}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                {m.text}
              </div>
            ))}

            {pending?.type === 'ask' && <div className="msg assistant">{pending.question}</div>}
            {pending?.type === 'choose_style' && (
              <StyleCards styles={pending.styles} disabled={busy} onPick={(s) => ask(s.id, s.name)} />
            )}

            {busy && (
              <div className="progress" role="status" aria-live="polite">
                {steps.map((s, i) => (
                  <span key={i} className="step">
                    {s}
                  </span>
                ))}
                <span className="now">Working on it…</span>
              </div>
            )}

            {outfits.length > 0 && (
              <section aria-label="Outfit suggestions">
                <div className="outfits">
                  {outfits.map((o, i) => (
                    <OutfitCard key={o.id} outfit={o} index={i} />
                  ))}
                </div>
              </section>
            )}

            {error && (
              <div className="error" role="alert">
                {error}
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="composer">
          <form onSubmit={submit}>
            <textarea
              rows={1}
              value={draft}
              maxLength={MAX}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onKey}
              placeholder={pending?.type === 'choose_style' ? 'Or describe your own style…' : 'e.g. College wear, around ₹4000'}
              aria-label="Your message"
              disabled={busy}
            />
            <button className="btn" type="submit" disabled={busy || !draft.trim()}>
              Send
            </button>
          </form>
          <div className="counter">
            {draft.length}/{MAX}
          </div>
        </div>
      </div>
    </div>
  )
}
