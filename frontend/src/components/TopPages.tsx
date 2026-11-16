import type { TopPage } from '../types'

export function TopPages({ pages, showWiki }: { pages: TopPage[]; showWiki: boolean }) {
  if (pages.length === 0) return <p className="muted">No edits in the last 5 minutes yet.</p>
  const max = pages[0].count
  return (
    <ol className="top-pages">
      {pages.map((p) => (
        <li key={`${p.wiki}:${p.title}`}>
          <div className="bar" style={{ width: `${(p.count / max) * 100}%` }} />
          <span className="title">
            {p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.title}</a> : p.title}
            {showWiki && <span className="tag">{p.wiki}</span>}
          </span>
          <span className="count">{p.count}</span>
        </li>
      ))}
    </ol>
  )
}
