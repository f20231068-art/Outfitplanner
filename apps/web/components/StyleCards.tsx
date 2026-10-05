import type { Style } from '../lib/types'

export default function StyleCards({
  styles,
  onPick,
  disabled,
}: {
  styles: Style[]
  onPick: (style: Style) => void
  disabled: boolean
}) {
  return (
    <section aria-label="Choose a style">
      <p className="styles-intro">Pick a style, or describe your own in the box below.</p>
      <div className="styles">
        {styles.map((s) => (
          <button key={s.id} className="style-card" onClick={() => onPick(s)} disabled={disabled}>
            <strong>{s.name}</strong>
            <span>{s.description}</span>
          </button>
        ))}
      </div>
    </section>
  )
}
