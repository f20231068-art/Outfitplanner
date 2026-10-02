// The shapes the API sends. Kept in one file so the UI and the backend contract are easy to compare.

export interface Item {
  product_id: string | null
  title: string
  retailer: string
  price_inr: number
  mrp_inr: number | null
  url: string
  url_kind: 'google_product_page' | 'retailer' | null
  image_url: string
  verification: { is_match?: boolean; confidence?: 'high' | 'low' } | null
}

export interface Outfit {
  id: string
  batch: number
  position: number
  style: string
  total_inr: number
  confidence: 'high' | 'low'
  rationale: string
  top: Item
  bottom: Item
}

export interface Style {
  id: string
  name: string
  description: string
  image_prompt: string
}

export type Pending =
  | { type: 'ask'; question: string; missing: string[] }
  | { type: 'choose_style'; styles: Style[] }

export interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

export interface ConversationSummary {
  id: string
  title: string
  updated_at: string
}

export interface ConversationDetail {
  id: string
  title: string
  messages: ChatMessage[]
  pending: Pending | null
  outfits: Outfit[]
}

export interface BuyLink {
  store: string
  url: string
  price_inr: number | null
  in_stock: boolean | null
  link_status: 'live' | 'dead' | 'unverified'
}

// One server-sent event from POST /conversations/{id}/messages
export type StreamEvent =
  | { event: 'status'; data: { stage: string; label: string } }
  | { event: 'interrupt'; data: Pending }
  | { event: 'outfits'; data: { outfits: Outfit[] } }
  | { event: 'message'; data: { role: 'assistant'; text: string } }
  | { event: 'error'; data: { message: string } }
  | { event: 'done'; data: Record<string, never> }
