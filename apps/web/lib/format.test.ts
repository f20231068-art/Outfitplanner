import { describe, expect, it } from 'vitest'
import { displayTitle, rupees } from './format'

describe('displayTitle', () => {
  it.each([
    ["Men's Olive Green Cargo Pants", 'Olive Green Cargo Pants'],
    ['Mens Black Slim Jeans', 'Black Slim Jeans'],
    ['Men Polo T-Shirt', 'Polo T-Shirt'],
    ['MEN’S Navy Blue Polo Shirt', 'Navy Blue Polo Shirt'],
    ["men's: Beige Chinos", 'Beige Chinos'],
    ['Blue Textured Polo T-Shirt for Men', 'Blue Textured Polo T-Shirt'],
    ["Charcoal Joggers - Men's", 'Charcoal Joggers'],
    ['Olive Henley | Men', 'Olive Henley'],
  ])('%s -> %s', (input, expected) => {
    expect(displayTitle(input)).toBe(expected)
  })

  it('leaves titles that merely contain the letters alone', () => {
    for (const t of ['Menswear Linen Shirt', 'Gentlemen Oxford Shirt', 'Women Kurta Set', 'Mentor Print Tee']) {
      expect(displayTitle(t)).toBe(t)
    }
  })

  it('never returns an empty name, and capitalises the first letter', () => {
    expect(displayTitle("Men's")).toBe("Men's")
    expect(displayTitle("Men's slim chinos")).toBe('Slim chinos')
    expect(displayTitle('  Polo ')).toBe('Polo')
  })
})

describe('rupees', () => {
  it('uses Indian digit grouping', () => {
    expect(rupees(1938)).toBe('₹1,938')
    expect(rupees(125000)).toBe('₹1,25,000')
  })
})
