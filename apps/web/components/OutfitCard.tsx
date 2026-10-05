'use client'

import { useState } from 'react'
import { ApiError, buyLink } from '../lib/api'
import { displayTitle, rupees } from '../lib/format'
import type { Item, Outfit } from '../lib/types'

function Piece({ item, label }: { item: Item; label: 'Top' | 'Bottom' }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<string | null>(null)
  const [broken, setBroken] = useState(false)

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

  const name = displayTitle(item.title)
  const showImage = item.image_url && !broken
  return (
    <div className="piece">
      <div className="store">
        <span>{item.retailer}</span>
        <span className="kind">{label}</span>
      </div>
      <div className="photo">
        {showImage ? (
          // thumbnails come from the store's own site; no-referrer stops them being blocked as hotlinks
          // eslint-disable-next-line @next/next/no-img-element
          <img src={item.image_url} alt={name} loading="lazy" referrerPolicy="no-referrer" onError={() => setBroken(true)} />
        ) : (
          <div className="none">
            <span>No photo available</span>
            <span>See it on {item.retailer}</span>
          </div>
        )}
        <button className="buy" onClick={buy} disabled={busy} aria-label={`Buy ${label.toLowerCase()} on ${item.retailer}`}>
          {busy ? 'Opening…' : 'Buy'}
        </button>
      </div>
      <div className="caption">
        <span className="title" title={name}>
          {name}
        </span>
        <span className="p">{rupees(item.price_inr)}</span>
      </div>
      {note && (
        <span className="notice" role="status">
          {note}
        </span>
      )}
    </div>
  )
}

export default function OutfitCard({ outfit }: { outfit: Outfit }) {
  return (
    // not shown on screen, but screen readers announce which outfit this is; shoppers point at one by position
    <article className="outfit" aria-label={`Outfit ${outfit.position}`}>
      <Piece item={outfit.top} label="Top" />
      <Piece item={outfit.bottom} label="Bottom" />
      <div className="total">{rupees(outfit.total_inr)}</div>
      <p className="rationale">{outfit.rationale}</p>
      {outfit.confidence === 'low' && <p className="notice">Check the store listing to confirm the details.</p>}
    </article>
  )
}

/** Placeholders shown while the outfits are being designed and searched. */
export function OutfitSkeletons({ count = 4 }: { count?: number }) {
  return (
    <div className="outfits" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="skeleton-card" />
      ))}
    </div>
  )
}
