// Pure reducer for dashboard state. Kept free of React and WebSocket code so it
// can be unit-tested directly.

import { editKey } from './types'
import type { ConnectionStatus, Edit, Flag, ServerMessage, Stats } from './types'

export const FEED_LIMIT = 200 // bounded so a long-running tab never grows unbounded
export const FLAG_LIMIT = 50

export interface State {
  status: ConnectionStatus
  wiki: string | null
  stats: Stats | null
  feed: Edit[] // newest first
  flags: Flag[] // newest first; kept separately because flags arrive after their edit
}

export type Action =
  | { kind: 'status'; status: ConnectionStatus }
  | { kind: 'select-wiki'; wiki: string | null }
  | { kind: 'message'; message: ServerMessage }

export const initialState: State = { status: 'connecting', wiki: null, stats: null, feed: [], flags: [] }

export function reducer(state: State, action: Action): State {
  switch (action.kind) {
    case 'status':
      return { ...state, status: action.status }

    case 'select-wiki':
      // Clear everything for the old selection right away, stats included, so
      // the new wiki never shows the previous one's numbers. The server answers
      // with a fresh `init`.
      return { ...state, wiki: action.wiki, stats: null, feed: [], flags: [] }

    case 'message': {
      const { message } = action
      // Ignore late messages for a wiki we've already switched away from.
      if (message.stats.wiki !== state.wiki) return state
      switch (message.type) {
        case 'init':
          return {
            ...state,
            stats: message.stats,
            feed: mergeFeed([], message.edits),
            flags: mergeFlags([], message.flags ?? []),
          }
        case 'tick':
          return {
            ...state,
            stats: message.stats,
            feed: mergeFeed(state.feed, message.edits),
            flags: mergeFlags(state.flags, message.flags ?? []),
          }
      }
    }
  }
}

function newestFirst<T>(items: T[]): T[] {
  return [...items].reverse() // server sends oldest first
}

/** Prepend items not already present (by key), dropping repeats within the batch too. */
function prependUnique<T>(existing: T[], incoming: T[], key: (item: T) => string, limit: number): T[] {
  if (incoming.length === 0) return existing
  const seen = new Set(existing.map(key))
  const fresh: T[] = []
  for (const item of newestFirst(incoming)) {
    const k = key(item)
    if (!seen.has(k)) {
      seen.add(k)
      fresh.push(item)
    }
  }
  return fresh.length ? [...fresh, ...existing].slice(0, limit) : existing
}

export const mergeFeed = (feed: Edit[], incoming: Edit[]): Edit[] =>
  prependUnique(feed, incoming, (e) => editKey(e.wiki, e.id), FEED_LIMIT)

export const mergeFlags = (flags: Flag[], incoming: Flag[]): Flag[] =>
  prependUnique(flags, incoming, (f) => editKey(f.wiki, f.edit_id), FLAG_LIMIT)
