/** Mastra scorers: thin wrappers that turn the plain rules into scorers Mastra can attach, store and chart. */

import { createScorer } from '@mastra/core/evals'
import type { SessionCase, SessionResult } from '../stylist/session'
import * as rules from './rules'

type Rule = (r: SessionResult, c: Partial<SessionCase>) => rules.Verdict

function wrap(id: string, name: string, description: string, rule: Rule) {
  const read = (run: { input?: unknown; output?: unknown }) => rule(run.output as SessionResult, (run.input ?? {}) as Partial<SessionCase>)
  return createScorer({ id, name, description })
    .generateScore(({ run }) => read(run).score)
    .generateReason(({ run }) => read(run).reason)
}

export const outfitCountScorer = wrap('four-outfits', 'Four outfits delivered', 'Did the shopper get the four outfits they were promised?', rules.outfitCount)
export const withinBudgetScorer = wrap('within-budget', 'Within budget', 'Is every outfit at or under the shopper\'s budget?', rules.withinBudget)
export const allVerifiedScorer = wrap('all-verified', 'Every item verified', 'Does every product shown carry a passing verification report?', rules.allItemsVerified)
export const followUpsScorer = wrap('follow-ups-handled', 'Follow-ups handled', 'Every message after the outfits gets a reply; change requests deliver new, in-budget, non-repeated outfits.', rules.followUpsHandled)
export const colourHiddenScorer = wrap('colour-hidden', 'Colour stays internal', 'The planner colour choices are not spelled out in the explanations shown to the shopper.', rules.rationaleHidesColours)
export const menswearScorer = wrap('menswear-only', 'Menswear only', 'No women\'s or kids\' clothing anywhere in the results.', rules.menswearOnly)
export const noDuplicatesScorer = wrap('no-duplicates', 'No duplicate products', 'The same product must not appear twice.', rules.noDuplicateProducts)
export const wishesScorer = wrap('wishes-honoured', 'Wishes honoured', 'Every product in a piece the shopper described (a white oversized t-shirt, denim baggy jeans) names what they asked for.', rules.shopperWishesHonoured)
export const varietyScorer = wrap('garment-variety', 'Garment variety', 'The four outfits use different tops and different bottoms.', rules.garmentVariety)
export const priceIntegrityScorer = wrap('price-integrity', 'Price integrity', 'Each outfit total is exactly its two prices added.', rules.priceIntegrity)
export const askedRightScorer = wrap('asks-only-whats-missing', 'Asks only what is missing', 'The agent asks for exactly the details the shopper left out.', rules.askedOnlyWhatIsMissing)
export const latencyScorer = wrap('latency', 'Latency', 'The whole session finishes within 60 seconds.', rules.latency)
export const noErrorsScorer = wrap('no-errors', 'No errors', 'No failures and no failed searches.', rules.noBackendErrors)
export const efficiencyScorer = wrap('call-efficiency', 'Call efficiency', 'A normal session needs about 10 model calls and 8 searches; far more means a loop or waste.', rules.callEfficiency)

/** Every scorer, keyed by the name used to register it. */
export const allScorers = {
  fourOutfits: outfitCountScorer,
  withinBudget: withinBudgetScorer,
  allVerified: allVerifiedScorer,
  followUpsHandled: followUpsScorer,
  colourHidden: colourHiddenScorer,
  menswearOnly: menswearScorer,
  noDuplicates: noDuplicatesScorer,
  wishesHonoured: wishesScorer,
  garmentVariety: varietyScorer,
  priceIntegrity: priceIntegrityScorer,
  asksOnlyWhatsMissing: askedRightScorer,
  latency: latencyScorer,
  noErrors: noErrorsScorer,
  callEfficiency: efficiencyScorer,
}
