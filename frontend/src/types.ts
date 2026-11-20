// Wire protocol shared with the backend (backend/app/pipeline.py).
// Messages are a discriminated union on `type`, so TypeScript forces every
// handler to deal with each shape explicitly.

export interface Edit {
  id: number
  wiki: string
  title: string
  user: string
  bot: boolean
  anonymous: boolean
  type: 'edit' | 'new'
  comment: string
  minor: boolean
  timestamp: number
  byte_delta: number | null // null when the stream didn't report sizes
  page_url: string
  diff_url: string | null
}

export interface TopPage {
  wiki: string
  title: string
  count: number
  url: string | null
}

export interface RatePoint {
  t: number
  rate: number
}

export interface Pulse {
  headline: string
  summary: string
  source: 'llm' | 'fallback'
  generated_at: number
}

export interface Flag {
  edit_id: number
  wiki: string
  title: string
  user: string
  confidence: number
  reason: string
  source: 'llm' | 'rules'
  diff_url: string | null
  created_at: number
  evidence: string | null // quote from the diff (AI flags only)
}

export interface Stats {
  wiki: string | null
  edits_per_minute: number
  series: RatePoint[]
  top_pages: TopPage[]
  wikis: { wiki: string; count: number }[]
  pulse: Pulse | null
  connected: boolean
  source: 'live' | 'replay'
  include_bots: boolean
  generated_at: number
}

export type ServerMessage =
  | { type: 'init'; stats: Stats; edits: Edit[]; flags: Flag[] }
  | { type: 'tick'; stats: Stats; edits: Edit[]; flags: Flag[] }

export type ClientMessage = { type: 'subscribe'; wiki: string | null }

export type ConnectionStatus = 'stopped' | 'connecting' | 'open' | 'closed'

/** Ids are only unique within one wiki. */
export const editKey = (wiki: string, id: number): string => `${wiki}:${id}`
