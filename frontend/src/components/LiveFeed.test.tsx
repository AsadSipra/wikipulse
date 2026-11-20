import { renderToStaticMarkup } from 'react-dom/server'
import type { Edit } from '../types'
import { LiveFeed } from './LiveFeed'

const edit = (overrides: Partial<Edit>): Edit => ({
  id: 1, wiki: 'enwiki', title: 'London', user: 'Alice', bot: false, anonymous: false, type: 'edit',
  comment: '', minor: false, timestamp: 1794996000, byte_delta: 10,
  page_url: 'https://en.wikipedia.org/wiki/London', diff_url: null, ...overrides,
})

// Both payloads appear in the edit comments of the provided sample recording.
test.each([
  '<script>alert("xss")</script> Updated description of the article.',
  '<img src=x onerror=alert("xss")> Minor formatting changes.',
])('edit text from the stream is shown as text, never as HTML: %s', (payload) => {
  const html = renderToStaticMarkup(<LiveFeed edits={[edit({ comment: payload, title: payload })]} flags={new Map()} />)
  expect(html).not.toContain('<script')
  expect(html).not.toContain('<img')
  expect(html).toContain('&lt;')
})
