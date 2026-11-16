// NOTE: to be reconciled with the provided LiveFeed.tsx starter once received.
import type { Edit } from '../types'

const timeFmt = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })

export function LiveFeed({ edits }: { edits: Edit[] }) {
  if (edits.length === 0) return <p className="muted">Listening for edits…</p>
  return (
    <ul className="feed">
      {edits.map((e) => (
        <li key={e.id} className={e.bot ? 'is-bot' : undefined}>
          <time>{timeFmt.format(e.timestamp * 1000)}</time>
          <span className="tag">{e.wiki}</span>
          <span className="title">
            <a href={e.diff_url ?? e.page_url} target="_blank" rel="noreferrer">{e.title}</a>
            {e.comment && <span className="comment">{e.comment}</span>}
          </span>
          <Delta value={e.byte_delta} />
          <span className="user">
            {e.user}
            {e.bot && <span className="tag">bot</span>}
            {e.anonymous && <span className="tag">anon</span>}
            {e.type === 'new' && <span className="tag">new</span>}
          </span>
        </li>
      ))}
    </ul>
  )
}

function Delta({ value }: { value: number }) {
  const cls = value > 0 ? 'delta pos' : value < 0 ? 'delta neg' : 'delta'
  return <span className={cls}>{value > 0 ? `+${value}` : value}</span>
}
