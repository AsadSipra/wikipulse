# WikiPulse

A live dashboard for Wikipedia edits: edits per minute, the 10 most-edited pages in the last 5 minutes, a filterable live feed, and AI features (trend summary, vandalism flags).

> **Status:** work in progress. Stream ingestion, rolling stats, WebSocket push and the dashboard are done. The AI features come next.

## Run it

**Docker (simplest)**

```bash
cp .env.example .env            # add LLM_API_KEY when the AI features land
docker compose up --build       # open http://localhost:8080
```

Offline or demo mode: `WIKIPULSE_SOURCE=replay docker compose up --build` replays `backend/data/sample_events.jsonl` instead of the live stream.

**Local development**

```bash
# backend (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload                  # live stream
WIKIPULSE_SOURCE=replay uvicorn app.main:app   # replay the sample file

# frontend (Node 20+), in another terminal
cd frontend
npm install
npm run dev                                    # http://localhost:5173
```

**Tests:** `cd backend && pytest` and `cd frontend && npm test`.

## How it works

```
Wikimedia SSE ─► LiveSource ─┐
                             ├─► parse_event ─► RollingStats ─► Pipeline ─(1s tick)─► Hub ─► WebSocket ─► React
sample .jsonl ─► ReplaySource┘                    (5-min window)              (per-client wiki filter)
```

| Module | Responsibility |
|---|---|
| `sources.py` | Live SSE client (reconnect with `Last-Event-ID`, jittered backoff) and a JSONL replay source behind the same interface |
| `models.py` | Normalises raw events into a typed `Edit`; drops untracked types, canary events and malformed input |
| `stats.py` | Sliding-window counts in per-second buckets with running totals |
| `pipeline.py` | Ingest loop plus a 1-second tick that pushes a snapshot and batched edits |
| `hub.py` | WebSocket fan-out with per-client wiki subscriptions; drops slow clients |
| `frontend/src/state.ts` | Pure reducer for dashboard state (unit-tested) |
| `frontend/src/useWikiPulse.ts` | WebSocket lifecycle: reconnect and re-subscribe |

## Decisions

- **O(1) rolling window.** Edits go into 1-second buckets, and the window keeps running totals. When a bucket expires, it is *subtracted* from the totals rather than re-scanning 5 minutes of edits, so the cost per event stays flat however busy the stream is. Keys that reach zero are deleted, so memory is bounded by what was edited inside the window.
- **Ingest time, not event time,** for windows. Replays then behave like live data, and the ~1s gap between event time and ingest time doesn't matter for "the last 5 minutes".
- **Batched pushes once a second** rather than one message per edit. This caps the message rate per client (and re-renders in the browser) during spikes.
- **Server-side wiki filtering.** A client watching a small wiki doesn't receive the full stream. A snapshot is computed once per distinct filter per tick and shared by every client using that filter.
- **Replay source behind the same interface.** It makes tests deterministic, allows offline development, and gives the live demo a fallback.
- **Plain SVG chart** instead of a chart library: one series doesn't justify the extra bundle size.
- **Same-origin `/ws`** in dev (Vite proxy) and production (nginx), so the frontend has no environment-specific URLs.

## Assumptions

- "Edits" means `edit` and `new` (page creation) events. Log and categorise events are ignored.
- All Wikimedia wikis are ingested; the wiki filter narrows the view.
- Bot edits are excluded from the stats (bots can dominate volume and drown out human trends) but still appear in the feed, labelled and dimmed. `INCLUDE_BOTS=true` changes this.
- IP editors and temporary accounts (`~YYYY-…`) are treated as anonymous. This is used as a signal for vandalism detection.

## What I'd do with more time

- Horizontal scaling: move fan-out to Redis pub/sub so several API instances share one ingester.
- Persist aggregates (e.g. per-minute counts in Postgres or TimescaleDB) for history beyond 5 minutes.
- Metrics (events/sec, lag, LLM latency and cost) and alerting on stream disconnects.
- Use Wikimedia's revert-risk model as an extra vandalism signal.
- Virtualise the feed list for very high-volume wikis.
