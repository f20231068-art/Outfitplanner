export const rupees = (n: number) => `₹${n.toLocaleString('en-IN')}`

/**
 * What the shopper reads as a product name. They know this is menswear, so a leading "Men's" / "Mens" / "Men" is
 * dropped, and so is a trailing "for Men". Only the display changes: the agent checks the store's full title.
 */
export function displayTitle(title: string): string {
  const clean = title
    .replace(/^\s*men(?:'s|s|’s)?\b[\s:,-]*/i, '')
    .replace(/[\s,|-]*(?:\bfor\b)?[\s,|-]*\bmen(?:'s|s|’s)?\s*$/i, '')
    .trim()
  return (clean || title.trim()).replace(/^./, (c) => c.toUpperCase())
}
