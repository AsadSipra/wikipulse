// NOTE: to be reconciled with the provided LiveFeed.tsx starter once received.
import { editKey } from '../types'
import type { Edit, Flag } from '../types'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })

// Two lines per edit: the title gets the full width on the first line, with
// the details underneath, so titles stay readable in a narrow panel.
export function LiveFeed({ edits, flags }: { edits: Edit[]; flags: Map<string, Flag> }) {
  if (edits.length === 0) return <p className="muted">Listening for edits…</p>
  return (
    <ul className="feed">
      {edits.map((e) => {
        const key = editKey(e.wiki, e.id)
        const flag = flags.get(key)
        const cls = [e.bot && 'is-bot', flag && 'is-flagged'].filter(Boolean).join(' ') || undefined
        return (
          <li key={key} className={cls}>
            <div className="feed-line">
              {flag && <span className="flag-icon" title={`Possible vandalism: ${flag.reason}`}>⚑</span>}
              <a className="title" dir="auto" href={e.diff_url ?? e.page_url} target="_blank" rel="noreferrer" title={e.title}>
                {e.title}
              </a>
              <Delta value={e.byte_delta} />
            </div>
            <div className="feed-meta">
              <time dateTime={new Date(e.timestamp * 1000).toISOString()}>{timeFmt.format(e.timestamp * 1000)}</time>
              <span className="tag">{e.wiki}</span>
              <span className="user">{e.user}</span>
              {e.bot && <span className="tag">bot</span>}
              {e.anonymous && <span className="tag">anon</span>}
              {e.type === 'new' && <span className="tag">new</span>}
              {e.comment && <span className="comment" dir="auto" title={e.comment}>{e.comment}</span>}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="delta" title="Size change not reported">–</span>
  const cls = value > 0 ? 'delta pos' : value < 0 ? 'delta neg' : 'delta'
  return <span className={cls}>{value > 0 ? `+${value.toLocaleString()}` : value.toLocaleString()}</span>
}
