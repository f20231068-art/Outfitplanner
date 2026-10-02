import type { ReactNode } from 'react'
import './globals.css'

export const metadata = {
  title: 'AI Stylist',
  description: 'Menswear outfits from Indian stores, matched to your budget.',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
