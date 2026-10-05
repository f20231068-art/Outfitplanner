'use client'

import { useEffect, useRef, useState } from 'react'
import type { ConversationSummary } from '../lib/types'
import { ChevronIcon, PlusIcon } from './icons'

/** The signed-in user at the bottom of the sidebar. The menu closes on Escape or a click elsewhere. */
function UserMenu({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const name = email.split('@')[0]

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false)
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
    }
  }, [open])

  return (
    <div className="user" ref={box}>
      {open && (
        <div className="menu" role="menu">
          <div className="who">Signed in as {email}</div>
          <button role="menuitem" onClick={onSignOut}>
            Log out
          </button>
        </div>
      )}
      <button className="user-chip" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="avatar" aria-hidden="true">
          {name.slice(0, 1).toUpperCase()}
        </span>
        <span className="user-name">{name}</span>
        <ChevronIcon />
      </button>
    </div>
  )
}

export default function Sidebar({
  email,
  convos,
  activeId,
  busy,
  open,
  onNew,
  onOpen,
  onSignOut,
}: {
  email: string
  convos: ConversationSummary[]
  activeId: string | null
  busy: boolean
  open: boolean // the slide-over state on small screens
  onNew: () => void
  onOpen: (id: string) => void
  onSignOut: () => void
}) {
  return (
    <>
      <aside className={`sidebar${open ? ' open' : ''}`} aria-label="Your looks">
        <span className="brand">Outfitmaxxing</span>
        <button className="btn light new" onClick={onNew} disabled={busy}>
          <PlusIcon /> New Look
        </button>
        <span className="recent-title">Recent looks</span>
        <nav className="convos" aria-label="Your conversations">
          {convos.length === 0 && <p className="empty-recent">Your looks will show up here.</p>}
          {convos.map((c) => (
            <button key={c.id} className="convo" aria-current={c.id === activeId} onClick={() => onOpen(c.id)} disabled={busy} title={c.title}>
              {c.title}
            </button>
          ))}
        </nav>
        <UserMenu email={email} onSignOut={onSignOut} />
      </aside>
      <div className="drawer-backdrop" aria-hidden="true" />
    </>
  )
}
