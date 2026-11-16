import { FEED_LIMIT, initialState, mergeFeed, reducer } from './state'
import type { Edit, Stats } from './types'

const edit = (id: number, wiki = 'enwiki'): Edit => ({
  id, wiki, title: `Page ${id}`, user: 'u', bot: false, anonymous: false, type: 'edit',
  comment: '', minor: false, timestamp: id, byte_delta: 1, page_url: '', diff_url: null,
})

const stats = (wiki: string | null = null): Stats => ({
  wiki, edits_per_minute: 1, series: [], top_pages: [], wikis: [], connected: true, generated_at: 0,
})

describe('reducer', () => {
  it('init replaces the feed, newest first', () => {
    const s = reducer(initialState, { kind: 'message', message: { type: 'init', stats: stats(), edits: [edit(1), edit(2)] } })
    expect(s.feed.map((e) => e.id)).toEqual([2, 1])
  })

  it('tick prepends new edits and skips duplicates', () => {
    let s = reducer(initialState, { kind: 'message', message: { type: 'init', stats: stats(), edits: [edit(1)] } })
    s = reducer(s, { kind: 'message', message: { type: 'tick', stats: stats(), edits: [edit(1), edit(2), edit(3)] } })
    expect(s.feed.map((e) => e.id)).toEqual([3, 2, 1])
  })

  it('ignores messages for a wiki we switched away from', () => {
    let s = reducer(initialState, { kind: 'select-wiki', wiki: 'dewiki' })
    s = reducer(s, { kind: 'message', message: { type: 'tick', stats: stats(null), edits: [edit(1)] } })
    expect(s.feed).toEqual([])
    expect(s.stats).toBeNull()
  })

  it('selecting a wiki clears the feed immediately', () => {
    let s = reducer(initialState, { kind: 'message', message: { type: 'init', stats: stats(), edits: [edit(1)] } })
    s = reducer(s, { kind: 'select-wiki', wiki: 'dewiki' })
    expect(s.feed).toEqual([])
    expect(s.wiki).toBe('dewiki')
  })
})

describe('mergeFeed', () => {
  it('caps the feed length', () => {
    const many = Array.from({ length: FEED_LIMIT + 50 }, (_, i) => edit(i))
    expect(mergeFeed([], many)).toHaveLength(FEED_LIMIT)
  })
})
