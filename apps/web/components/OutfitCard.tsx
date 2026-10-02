'use client'

import { useState } from 'react'
import { ApiError, buyLink } from '../lib/api'
import type { Item, Outfit } from '../lib/types'

const rupees = (n: number) => `₹${n.toLocaleString('en-IN')}`

function Piece({ item, label }: { item: Item; label: 'Top' | 'Bottom' }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)

  async function buy() {
    setNote(null)
    // Open the tab NOW, inside the click, so the browser's pop-up blocker allows it; the real address
    // is filled in once the server has found the store's own page.
    const tab = window.open('', '_blank')
    if (tab) tab.opener = null
    setBusy(true)
    try {
      if (!item.product_id) throw new ApiError('No store link for this item.', 404)
      const link = await buyLink(item.product_id)
      if (link.link_status === 'dead') {
        tab?.close()
        setNote('That listing seems to be gone. Try another outfit.')
        return
      }
      if (tab) tab.location.href = link.url
      else window.location.href = link.url
      if (link.in_stock === false) setNote('The store lists this as out of stock.')
      else if (link.link_status === 'unverified') setNote('Opened, but the store blocks automatic checks, so we could not confirm it is in stock.')
    } catch (err) {
      tab?.close()
      setNote(err instanceof ApiError ? err.message : 'Could not open the store page. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="piece">
      <span className="label">{label}</span>
      {/* thumbnails come from the store's CDN; no-referrer stops them being blocked as hotlinks */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={item.image_url} alt={item.title} loading="lazy" referrerPolicy="no-referrer" />
      <span className="title" title={item.title}>
        {item.title}
      </span>
      <span className="meta">
        <span className="price">{rupees(item.price_inr)}</span>
        {item.mrp_inr && item.mrp_inr > item.price_inr ? <s> {rupees(item.mrp_inr)}</s> : null} · {item.retailer}
      </span>
      <button className="btn small" onClick={buy} disabled={busy} aria-label={`Buy ${label.toLowerCase()} on ${item.retailer}`}>
        {busy ? 'Opening…' : 'Buy'}
      </button>
      {note && (
        <span className="notice" role="status">
          {note}
        </span>
      )}
    </div>
  )
}

export default function OutfitCard({ outfit, index }: { outfit: Outfit; index: number }) {
  return (
    <article className="outfit" aria-label={`Outfit ${index + 1}`}>
      <div className="outfit-head">
        <span className="total">{rupees(outfit.total_inr)}</span>
        <span className={`badge ${outfit.confidence}`} title="We read the colour from the store listing when it states one">
          {outfit.confidence === 'high' ? 'Colour confirmed' : 'Colour not confirmed'}
        </span>
      </div>
      <div className="pair">
        <Piece item={outfit.top} label="Top" />
        <Piece item={outfit.bottom} label="Bottom" />
      </div>
      <p className="rationale">{outfit.rationale}</p>
    </article>
  )
}
