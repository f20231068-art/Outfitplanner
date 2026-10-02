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
      <p style={{ marginBottom: 8, color: 'var(--muted)' }}>Pick a style, or type your own below.</p>
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
