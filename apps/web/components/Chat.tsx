'use client'

import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, createConversation, getConversation, listConversations, logout, me, refreshSession, sendMessage } from '../lib/api'
import type { ChatMessage, ConversationSummary, Outfit, Pending } from '../lib/types'
import Composer from './Composer'
import { MenuIcon } from './icons'
import OutfitCard, { OutfitSkeletons } from './OutfitCard'
import Sidebar from './Sidebar'
import StyleCards from './StyleCards'

const EXAMPLES = ['College wear, around ₹4000', 'Smart casual for office, under ₹6000', 'Party look, ₹5000']
// once one of these steps has finished, outfits are being built: show placeholders where the cards will go
const BUILDING = ['Style chosen', 'Understood your change', 'Outfits designed', 'Stores searched']

/** True on phone-sized screens, where the input is too narrow for a long placeholder. */
function useNarrow() {
  const [narrow, setNarrow] = useState(false)
  useEffect(() => {
    const q = window.matchMedia('(max-width: 600px)')
    const update = () => setNarrow(q.matches)
    update()
    q.addEventListener('change', update)
    return () => q.removeEventListener('change', update)
  }, [])
  return narrow
}

export default function Chat() {
  const router = useRouter()
  const narrow = useNarrow()
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
  const [navOpen, setNavOpen] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)
  const last = useRef<{ text: string; styleId?: string } | null>(null) // for "Try again" after an error

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
    setNavOpen(false)
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

  async function ask(text: string, styleId?: string, again = false) {
    const clean = text.trim()
    if (!clean || busy) return
    last.current = { text: clean, styleId }
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
      if (!again) setMessages((m) => [...m, { role: 'user', text: clean }])
      for await (const ev of sendMessage(id, clean, styleId)) {
        if (ev.event === 'status') setSteps((s) => [...s, ev.data.label])
        else if (ev.event === 'pending') setPending(ev.data)
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

  async function signOut() {
    await logout().catch(() => {})
    router.replace('/login')
  }

  if (email === null) {
    return (
      <div className="auth" aria-busy="true">
        <p style={{ color: 'var(--muted)' }}>Loading your looks…</p>
      </div>
    )
  }

  const empty = messages.length === 0 && !pending && !busy
  // outfits come in sets (one per search); a later set never replaces an earlier one
  const batches = [...new Set(outfits.map((o) => o.batch))].sort((a, b) => a - b).map((b) => outfits.filter((o) => o.batch === b))
  const building = busy && steps.some((s) => BUILDING.includes(s))
  const placeholder =
    pending?.type === 'choose_style'
      ? narrow ? 'Pick a style or type your own' : 'Pick a style above, or describe your own…'
      : outfits.length > 0
        ? narrow ? 'Ask for a change…' : 'Ask for changes: cheaper, a different top, more like the 2nd one…'
        : narrow ? 'Occasion and budget…' : 'Tell me the occasion and your budget, e.g. college wear, around ₹4000'

  return (
    <div className="app">
      <Sidebar
        email={email}
        convos={convos}
        activeId={activeId}
        busy={busy}
        open={navOpen}
        onNew={reset}
        onOpen={(id) => {
          setNavOpen(false)
          open(id)
        }}
        onSignOut={signOut}
      />

      {/* the stage holds the conversation and the purple gradient behind it */}
      <div className="stage">
      <main className="center">
        <header className="mobilebar">
          <button className="iconbtn" aria-label="Open your looks" onClick={() => setNavOpen((o) => !o)}>
            <MenuIcon />
          </button>
          <span className="brand">Outfitmaxxing</span>
        </header>

        <div className="thread">
          <div className="thread-inner" role="log" aria-label="Conversation" aria-live="polite">
            {empty && (
              <div className="welcome">
                <h2>What are you shopping for?</h2>
                <p>Tell me the occasion and your budget in rupees. I will suggest styles, then find outfits from India&apos;s best menswear brands.</p>
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
            {pending?.type === 'choose_style' && <StyleCards styles={pending.styles} disabled={busy} onPick={(s) => ask(s.name, s.id)} />}

            {busy && (
              <div className="progress" role="status">
                {steps.map((s, i) => (
                  <span key={i} className="step">
                    {s}
                  </span>
                ))}
                <span className="now">Working on it…</span>
              </div>
            )}

            {batches.map((set, n) => (
              <section key={set[0].batch} aria-label={`Outfit suggestions, set ${n + 1}`}>
                {batches.length > 1 && <h3 className="set-title">{n === 0 ? 'First set' : `Set ${n + 1}`}</h3>}
                <div className="outfits" tabIndex={0} aria-label={`Outfits, set ${n + 1}: scroll sideways to see them all`}>
                  {set.map((o) => (
                    <OutfitCard key={o.id} outfit={o} />
                  ))}
                </div>
              </section>
            ))}
            {building && <OutfitSkeletons />}

            {error && (
              <div className="error" role="alert">
                <span>{error}</span>
                {last.current && (
                  <button className="btn small ghost" onClick={() => ask(last.current!.text, last.current!.styleId, true)} disabled={busy}>
                    Try again
                  </button>
                )}
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <Composer draft={draft} setDraft={setDraft} onSend={(t) => ask(t)} busy={busy} placeholder={placeholder} />
      </main>

      </div>
    </div>
  )
}
