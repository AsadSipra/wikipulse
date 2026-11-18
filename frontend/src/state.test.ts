import { FEED_LIMIT, initialState, mergeFeed, mergeFlags, reducer } from './state'
import type { Edit, Flag, Stats } from './types'

const edit = (id: number, wiki = 'enwiki'): Edit => ({
  id, wiki, title: `Page ${id}`, user: 'u', bot: false, anonymous: false, type: 'edit',
  comment: '', minor: false, timestamp: id, byte_delta: 1, page_url: '', diff_url: null,
})

const stats = (wiki: string | null = null): Stats => ({
  wiki, edits_per_minute: 1, series: [], top_pages: [], wikis: [], pulse: null, connected: true,
  source: 'live', include_bots: false, generated_at: 0,
})

describe('reducer', () => {
  it('init replaces the feed, newest first', () => {
    const s = reducer(initialState, { kind: 'message', message: { type: 'init', stats: stats(), edits: [edit(1), edit(2)], flags: [] } })
    expect(s.feed.map((e) => e.id)).toEqual([2, 1])
  })

  it('tick prepends new edits and skips duplicates', () => {
    let s = reducer(initialState, { kind: 'message', message: { type: 'init', stats: stats(), edits: [edit(1)], flags: [] } })
    s = reducer(s, { kind: 'message', message: { type: 'tick', stats: stats(), edits: [edit(1), edit(2), edit(3)], flags: [] } })
    expect(s.feed.map((e) => e.id)).toEqual([3, 2, 1])
  })

  it('ignores messages for a wiki we switched away from', () => {
    let s = reducer(initialState, { kind: 'select-wiki', wiki: 'dewiki' })
    s = reducer(s, { kind: 'message', message: { type: 'tick', stats: stats(null), edits: [edit(1)], flags: [] } })
    expect(s.feed).toEqual([])
    expect(s.stats).toBeNull()
  })

  it('selecting a wiki clears the feed and the old stats immediately', () => {
    let s = reducer(initialState, { kind: 'message', message: { type: 'init', stats: stats(), edits: [edit(1)], flags: [] } })
    s = reducer(s, { kind: 'select-wiki', wiki: 'dewiki' })
    expect(s.feed).toEqual([])
    expect(s.stats).toBeNull() // regression: the previous wiki's numbers stayed on screen
    expect(s.wiki).toBe('dewiki')
  })

  it('keeps edits with the same id on different wikis apart', () => {
    const s = reducer(initialState, {
      kind: 'message',
      message: { type: 'tick', stats: stats(), edits: [edit(7, 'enwiki'), edit(7, 'dewiki')], flags: [] },
    })
    expect(s.feed.map((e) => e.wiki)).toEqual(['dewiki', 'enwiki'])
  })

  it('drops repeats inside a single batch', () => {
    const s = reducer(initialState, {
      kind: 'message',
      message: { type: 'tick', stats: stats(), edits: [edit(1), edit(1), edit(2)], flags: [] },
    })
    expect(s.feed.map((e) => e.id)).toEqual([2, 1])
  })
})

describe('mergeFeed', () => {
  it('caps the feed length', () => {
    const many = Array.from({ length: FEED_LIMIT + 50 }, (_, i) => edit(i))
    expect(mergeFeed([], many)).toHaveLength(FEED_LIMIT)
  })
})

const flag = (id: number): Flag => ({
  edit_id: id, wiki: 'enwiki', title: 't', user: 'u', confidence: 0.9, reason: 'r',
  source: 'llm', diff_url: null, created_at: id, evidence: null,
})

describe('mergeFlags', () => {
  it('prepends new flags and ignores repeats', () => {
    expect(mergeFlags([flag(1)], [flag(1), flag(2)]).map((f) => f.edit_id)).toEqual([2, 1])
  })

  it('tick carries flags into state', () => {
    const s = reducer(initialState, { kind: 'message', message: { type: 'tick', stats: stats(), edits: [], flags: [flag(7)] } })
    expect(s.flags.map((f) => f.edit_id)).toEqual([7])
  })
})
