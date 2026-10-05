import localFont from 'next/font/local'
import type { ReactNode } from 'react'
import './globals.css'

// Inter Medium only (500): the whole interface uses this one weight. The file is part of the app, so no font
// service is called at build or run time.
const inter = localFont({ src: './fonts/Inter-Medium.woff2', weight: '500', style: 'normal', display: 'swap', variable: '--font-sans' })

export const metadata = {
  title: 'Outfitmaxxing',
  description: 'Menswear outfits from Indian stores, matched to your budget.',
}

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body>{children}</body>
    </html>
  )
}
