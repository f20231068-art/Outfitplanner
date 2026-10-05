/** Small inline icons: no icon library to download, and they take the surrounding text colour. */

type P = { size?: number }
const base = (size = 20) => ({ width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true })

export const SendIcon = ({ size = 22 }: P) => (
  <svg {...base(size)} fill="currentColor" stroke="none">
    <path d="M3.4 20.4 21 12 3.4 3.6 3.3 10.1 15 12 3.3 13.9z" />
  </svg>
)
export const MenuIcon = ({ size }: P) => (
  <svg {...base(size)}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </svg>
)
export const ChevronIcon = ({ size = 16 }: P) => (
  <svg {...base(size)}>
    <path d="m6 15 6-6 6 6" />
  </svg>
)
export const PlusIcon = ({ size = 16 }: P) => (
  <svg {...base(size)}>
    <path d="M12 5v14M5 12h14" />
  </svg>
)
