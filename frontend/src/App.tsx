import { LiveFeed } from './components/LiveFeed'
import { RateChart } from './components/RateChart'
import { TopPages } from './components/TopPages'
import { useWikiPulse } from './useWikiPulse'

export default function App() {
  const { state, selectWiki } = useWikiPulse()
  const { stats, feed, status, wiki } = state
  const live = status === 'open' && (stats?.connected ?? true)

  return (
    <div className="app">
      <header>
        <h1>WikiPulse</h1>
        <span className={`status ${live ? 'ok' : 'down'}`}>
          {status === 'open' ? (stats?.connected === false ? 'Stream reconnecting' : 'Live') : 'Reconnecting'}
        </span>
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
        <section className="card rate">
          <h2>Edits per minute</h2>
          <p className="big">{stats?.edits_per_minute ?? '–'}</p>
          <RateChart series={stats?.series ?? []} />
          <p className="muted small">Human edits; bots excluded from stats.</p>
        </section>

        <section className="card top">
          <h2>Top 10 pages · last 5 min</h2>
          <TopPages pages={stats?.top_pages ?? []} showWiki={wiki === null} />
        </section>

        <section className="card feed-card">
          <h2>Live feed</h2>
          <LiveFeed edits={feed} />
        </section>
      </main>
    </div>
  )
}
