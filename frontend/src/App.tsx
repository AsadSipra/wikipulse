import { useMemo } from 'react'
import { FlaggedEdits } from './components/FlaggedEdits'
import { LiveFeed } from './components/LiveFeed'
import { PulseCard } from './components/PulseCard'
import { RateChart } from './components/RateChart'
import { TopPages } from './components/TopPages'
import { editKey } from './types'
import type { ConnectionStatus, Stats } from './types'
import { useWikiPulse } from './useWikiPulse'

export default function App() {
  const { state, selectWiki } = useWikiPulse()
  const { stats, feed, flags, status, wiki } = state
  const flagsByEdit = useMemo(() => new Map(flags.map((f) => [editKey(f.wiki, f.edit_id), f])), [flags])
  const connection = connectionLabel(status, stats)

  return (
    <div className="app">
      <header>
        <h1>WikiPulse</h1>
        <span className={`status ${connection.tone}`} role="status">{connection.text}</span>
        <label className="filter">
          Wiki
          <select value={wiki ?? ''} onChange={(e) => selectWiki(e.target.value || null)}>
            <option value="">All wikis</option>
            {/* Keep the current choice listed even if it has no edits right now. */}
            {wiki && !stats?.wikis.some((w) => w.wiki === wiki) && <option value={wiki}>{wiki}</option>}
            {stats?.wikis.map((w) => (
              <option key={w.wiki} value={w.wiki}>{w.wiki} ({w.count})</option>
            ))}
          </select>
        </label>
      </header>

      <main>
        <section className="card pulse-card">
          <h2>
            Pulse · what's trending across all Wikipedias
            {wiki && <span className="scope-note"> · not filtered to {wiki}</span>}
          </h2>
          <PulseCard pulse={stats?.pulse ?? null} />
        </section>

        <section className="card rate">
          <h2>Edits per minute{wiki && ` · ${wiki}`}</h2>
          <p className="big">{stats?.edits_per_minute ?? '–'}</p>
          <RateChart series={stats?.series ?? []} />
          <p className="muted small">
            Headline: edits in the last 60 seconds. Chart: 10-second slices scaled to per minute.
            {stats && (stats.include_bots ? ' Bots included.' : ' Bots excluded.')}
          </p>
        </section>

        <section className="card top">
          <h2>Top 10 articles · edits in the last 5 min</h2>
          <TopPages pages={stats?.top_pages ?? []} showWiki={wiki === null} />
        </section>

        <section className="card feed-card">
          <h2>Live feed</h2>
          <LiveFeed edits={feed} flags={flagsByEdit} />
        </section>

        <section className="card flags-card">
          <h2>Possible vandalism</h2>
          <FlaggedEdits flags={flags} />
        </section>
      </main>
    </div>
  )
}

function connectionLabel(status: ConnectionStatus, stats: Stats | null): { text: string; tone: string } {
  if (status === 'paused') return { text: 'Paused while the tab was hidden', tone: 'down' }
  if (status === 'connecting' && !stats) return { text: 'Connecting…', tone: 'down' }
  if (status !== 'open') return { text: 'Reconnecting…', tone: 'down' }
  if (!stats) return { text: 'Loading…', tone: 'down' }
  if (stats.source === 'replay') {
    return stats.connected ? { text: 'Replay (recorded data)', tone: 'replay' } : { text: 'Replay ended', tone: 'down' }
  }
  return stats.connected ? { text: 'Live', tone: 'ok' } : { text: 'Wikipedia stream reconnecting…', tone: 'down' }
}
