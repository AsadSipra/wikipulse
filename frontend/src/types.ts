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
  byte_delta: number
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

export interface Stats {
  wiki: string | null
  edits_per_minute: number
  series: RatePoint[]
  top_pages: TopPage[]
  wikis: { wiki: string; count: number }[]
  connected: boolean
  generated_at: number
}

export type ServerMessage =
  | { type: 'init'; stats: Stats; edits: Edit[] }
  | { type: 'tick'; stats: Stats; edits: Edit[] }

export type ClientMessage = { type: 'subscribe'; wiki: string | null }

export type ConnectionStatus = 'connecting' | 'open' | 'closed'
