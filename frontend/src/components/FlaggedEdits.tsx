import { editKey } from '../types'
import type { Flag } from '../types'

// Own list: a flag can arrive after its edit has scrolled out of the feed.
export function FlaggedEdits({ flags }: { flags: Flag[] }) {
  if (flags.length === 0) return <p className="muted">No suspicious edits flagged yet.</p>
  return (
    <ul className="flags">
      {flags.map((f) => (
        <li key={editKey(f.wiki, f.edit_id)}>
          <div className="flag-top">
            {f.diff_url
              ? <a href={f.diff_url} target="_blank" rel="noreferrer" className="title" dir="auto">{f.title}</a>
              : <span className="title" dir="auto">{f.title}</span>}
            <span className="tag">{f.wiki}</span>
            {f.source === 'llm'
              ? <span className="confidence" title="Model confidence">{Math.round(f.confidence * 100)}%</span>
              : <span className="confidence rules">rules</span>}
          </div>
          <p className="flag-reason">{f.reason}</p>
          {f.evidence && <blockquote className="flag-evidence" title="Quoted from the diff">{f.evidence}</blockquote>}
          <p className="muted small">
            by {f.user} · {f.source === 'llm' ? 'AI review' : 'strong rule match, not reviewed by AI'}
          </p>
        </li>
      ))}
    </ul>
  )
}
