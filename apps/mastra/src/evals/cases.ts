/**
 * The evaluation dataset: realistic shopper requests, each with the ground truth the scorers check.
 *
 * `expect.budget`  what the outfits must stay under
 * `expect.asks`    what the agent SHOULD ask for because the shopper left it out
 * `answers`        what the simulated shopper replies if asked
 */

import type { SessionCase } from '../mastra/stylist/session'

const ANSWERS = { budget: 'around 3000 rupees', occasion: 'college' }

export const cases: SessionCase[] = [
  // ---- complete requests: no questions needed, straight to styles -----------------------------------------
  { id: 'college-4000', prompt: 'I need a smart casual look for college, around 4000 rupees', style: 1, expect: { budget: 4000, asks: [] } },
  { id: 'office-6000', prompt: 'Office wear for a new job, budget 6000', style: 'minimalist', expect: { budget: 6000, asks: [] } },
  { id: 'party-5000', prompt: 'Something for a party this weekend, ₹5,000', style: 0, expect: { budget: 5000, asks: [] } },
  { id: 'wedding-8000', prompt: 'Outfits for a cousin\'s wedding, up to 8000 rupees', style: 2, expect: { budget: 8000, asks: [] } },
  { id: 'casual-2500', prompt: 'Everyday casual clothes under 2500 rupees', style: 'korean-casual', expect: { budget: 2500, asks: [] } },
  { id: 'gym-2000', prompt: 'Gym and casual wear, 2k budget', style: 4, expect: { budget: 2000, asks: [] } },
  { id: 'travel-3500', prompt: 'Travel outfits for a trip, around 3.5k', style: 3, expect: { budget: 3500, asks: [] } },
  { id: 'tight-1500', prompt: 'College wear, strictly under 1500 rupees', style: 0, expect: { budget: 1500, asks: [] } },
  { id: 'generous-15000', prompt: 'Party outfits, I can spend 15000', style: 1, expect: { budget: 15000, asks: [] } },

  // ---- the shopper describes the pieces: every product must be what they described ----------------------------
  { id: 'wish-white-tee-denim', prompt: 'I want a white oversized tshirt and denim baggy jeans, budget 4500, for a college fest', style: 0,
    expect: { budget: 4500, asks: [], wishes: { top: ['white|ivory', 't-shirt|tee|tshirt'], bottom: ['jeans|denim'] } } },
  { id: 'wish-navy-chinos', prompt: 'Navy chinos with a white shirt for the office, 6000 rupees', style: 1,
    expect: { budget: 6000, asks: [], wishes: { top: ['white', 'shirt'], bottom: ['navy|blue', 'chino'] } } },
  { id: 'wish-olive-cargos', prompt: 'Olive green cargo pants with a plain black t-shirt, everyday wear, around 3500', style: 0,
    expect: { budget: 3500, asks: [], wishes: { top: ['black', 't-shirt|tee|tshirt'], bottom: ['olive|green', 'cargo'] } } },
  { id: 'wish-only-bottom', prompt: 'White baggy jeans for a party, budget 5000', style: 2,
    expect: { budget: 5000, asks: [], wishes: { bottom: ['white|off white|ivory', 'jeans|denim'] } } },
  { id: 'wish-grey-hoodie', prompt: 'A grey hoodie with black joggers for the gym, 3000 rupees', style: 0,
    expect: { budget: 3000, asks: [], wishes: { top: ['grey|gray|charcoal', 'hoodie'], bottom: ['black', 'jogger'] } } },

  // ---- incomplete requests: the agent must ask for exactly what is missing ---------------------------------
  { id: 'missing-budget', prompt: 'I need clothes for college', answers: ANSWERS, style: 0, expect: { budget: 3000, asks: ['budget'] } },
  { id: 'missing-occasion', prompt: 'My budget is 4500 rupees', answers: ANSWERS, style: 1, expect: { budget: 4500, asks: ['occasion'] } },
  { id: 'missing-both', prompt: 'Help me find something to wear', answers: ANSWERS, style: 2, expect: { budget: 3000, asks: ['budget', 'occasion'] } },
  { id: 'vague-no-numbers', prompt: 'casual stuff please', answers: ANSWERS, style: 0, expect: { budget: 3000, asks: ['budget'] } },

  // ---- the conversation never ends: messages typed after the outfits arrive ---------------------------------
  { id: 'follow-cheaper', prompt: 'College wear, around 4000 rupees', style: 1, expect: { budget: 4000, asks: [] },
    followUps: [{ say: 'Show me cheaper options', expect: { outfits: true, budget: 3200 } }] },
  { id: 'follow-compound', prompt: 'Office wear for a new job, budget 6000', style: 0, expect: { budget: 6000, asks: [] },
    followUps: [{ say: 'Show more like the 3rd one, but cheaper options, and change the color of the bottom to purple, under 1500', expect: { outfits: true, budget: 1500 } }] },
  { id: 'follow-question', prompt: 'Party look, budget 5000', style: 2, expect: { budget: 5000, asks: [] },
    followUps: [{ say: 'Why is the first one a good pick?', expect: { outfits: false } }] },
  { id: 'follow-chain', prompt: 'Everyday casual clothes under 3000 rupees', style: 3, expect: { budget: 3000, asks: [] },
    followUps: [
      { say: 'Something different please', expect: { outfits: true, budget: 3000 } },
      { say: 'Thanks!', expect: { outfits: false } },
    ] },
]
