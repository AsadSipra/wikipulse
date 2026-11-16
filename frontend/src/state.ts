// Pure reducer for dashboard state. Kept free of React and WebSocket code so it
// can be unit-tested directly.

import type { ConnectionStatus, Edit, ServerMessage, Stats } from './types'

export const FEED_LIMIT = 200 // bounded so a long-running tab never grows unbounded

export interface State {
  status: ConnectionStatus
  wiki: string | null
  stats: Stats | null
  feed: Edit[] // newest first
}

export type Action =
  | { kind: 'status'; status: ConnectionStatus }
  | { kind: 'select-wiki'; wiki: string | null }
  | { kind: 'message'; message: ServerMessage }

export const initialState: State = { status: 'connecting', wiki: null, stats: null, feed: [] }

export function reducer(state: State, action: Action): State {
  switch (action.kind) {
    case 'status':
      return { ...state, status: action.status }

    case 'select-wiki':
      // Clear the feed right away; the server answers with a fresh `init`.
      return { ...state, wiki: action.wiki, feed: [] }

    case 'message': {
      const { message } = action
      // Ignore late messages for a wiki we've already switched away from.
      if (message.stats.wiki !== state.wiki) return state
      switch (message.type) {
        case 'init':
          return { ...state, stats: message.stats, feed: newestFirst(message.edits).slice(0, FEED_LIMIT) }
        case 'tick':
          return { ...state, stats: message.stats, feed: mergeFeed(state.feed, message.edits) }
      }
    }
  }
}

function newestFirst(edits: Edit[]): Edit[] {
  return [...edits].reverse() // server sends oldest first
}

export function mergeFeed(feed: Edit[], incoming: Edit[]): Edit[] {
  if (incoming.length === 0) return feed
  const seen = new Set(feed.map((e) => e.id))
  const fresh = newestFirst(incoming).filter((e) => !seen.has(e.id))
  return [...fresh, ...feed].slice(0, FEED_LIMIT)
}
