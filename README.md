# WikiPulse

A live dashboard for Wikipedia edits: edits per minute, the 10 most-edited pages in the last 5 minutes, a filterable live feed, and AI features (trend summary, vandalism flags).

> **Status:** feature-complete for the brief: live ingestion, rolling stats, WebSocket push, dashboard with wiki filter, Pulse summary and vandalism flags, with unit, integration and end-to-end tests. Open item: the brief's starter files (`LiveFeed.tsx`, `stream_client.py`, `sample_events.jsonl`) had not arrived when this was written, so the code and the sample recording are my own (see Known limitations).

## Run it

**Docker (simplest)**

```bash
cp .env.example .env            # pick the LLM (defaults to Ollama on this machine)
docker compose up --build       # open http://localhost:8080
```

Offline or demo mode: `WIKIPULSE_SOURCE=replay docker compose up --build` replays `backend/data/sample_events.jsonl` instead of the live stream. The dashboard labels this as recorded data.

Every setting in `.env` is passed to the backend container. With Ollama, set `DOCKER_LLM_BASE_URL=http://host.docker.internal:11434/v1`, because `localhost` inside the container is the container itself.

**Local development**

```bash
# backend (Python 3.11+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --env-file ../.env   # live stream
WIKIPULSE_SOURCE=replay uvicorn app.main:app   # replay the sample file

# frontend (Node 20+), in another terminal
cd frontend
npm install
npm run dev                                    # http://localhost:5173
```

**Tests**

```bash
cd backend && pytest              # unit + API/WebSocket integration tests
cd frontend && npm test           # reducer unit tests (Vitest)
cd frontend && npx playwright install chromium && npm run test:e2e   # one browser test
```

The end-to-end test starts its own backend (replaying the sample with AI off, so it is deterministic and makes no paid calls) and Vite dev server on spare ports, then checks the dashboard fills in and that the wiki filter narrows every panel. I used Playwright rather than C# Selenium to keep the whole frontend toolchain in TypeScript; it waits for elements automatically, which avoids timing flakiness with a live-updating page.

**AI setup.** Any OpenAI-compatible endpoint works; it's chosen with `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY`.

| Provider | `LLM_BASE_URL` | `LLM_MODEL` |
|---|---|---|
| Ollama (local, default) | `http://localhost:11434/v1` | e.g. `llama3.2` (`ollama pull llama3.2`) |
| OpenAI | `https://api.openai.com/v1` | e.g. `gpt-4o-mini` |
| Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | e.g. `gemini-2.0-flash` |
| Anthropic | `https://api.anthropic.com/v1` | e.g. `claude-haiku-5-5` |

If the model is unreachable, the dashboard still works: the Pulse card shows a summary built from the numbers, and only strong rule matches are flagged. `GET /health` shows LLM calls, failures (with a redacted error) and budget usage, plus seconds since the last stream event. It returns **503 with `status: down`** if the ingestion pipeline has stopped, which is also what Docker's healthcheck uses.

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
| `llm.py` | OpenAI-compatible client, tolerant JSON parsing, per-feature call budgets |
| `pulse.py` | Trend summary on a timer, with change detection and a numbers-only fallback |
| `vandalism.py` | Rule-based pre-filter, then LLM review of the actual diff for candidates only |
| `frontend/src/state.ts` | Pure reducer for dashboard state (unit-tested) |
| `frontend/src/useWikiPulse.ts` | WebSocket lifecycle: reconnect and re-subscribe |

## Decisions

- **Constant-time recording in the rolling window.** Edits go into 1-second buckets, and the window keeps running totals. When a bucket expires, it is *subtracted* from the totals rather than re-scanning 5 minutes of edits, so recording an edit costs the same however busy the stream is. Keys that reach zero are deleted, so memory is bounded by what was edited inside the window. Reading is not constant: the top 10 sorts the pages active in the window, and each distinct wiki filter builds its own snapshot once per second. At Wikipedia's volume that is cheap, but I haven't profiled it.
- **Ingest time, not event time,** for windows. Replays then behave like live data, and the ~1s gap between event time and ingest time doesn't matter for "the last 5 minutes".
- **Batched pushes once a second** rather than one message per edit. This caps the message rate per client (and re-renders in the browser) during spikes.
- **Server-side wiki filtering.** A client watching a small wiki doesn't receive the full stream. A snapshot is computed once per distinct filter per tick and shared by every client using that filter.
- **Replay source behind the same interface.** It makes tests deterministic, allows offline development, and gives the live demo a fallback.
- **Plain SVG chart** instead of a chart library: one series doesn't justify the extra bundle size.
- **Pulse runs on a timer, not per request.** Cost is fixed however many people have the dashboard open, and the LLM call is skipped when the top pages haven't changed. If one refresh fails, a summary under 3 minutes old is kept rather than replaced with the numbers-only version.
- **Only Wikipedia, and only articles trend.** On the live stream, Wikidata's bulk-tool edits (not flagged as bots) filled the whole top 10 with item IDs like `Q141401630`, and on English Wikipedia user sandboxes and noticeboards crowded out articles. Sister projects are dropped at ingest (`WIKIPEDIA_ONLY`), and only namespace-0 articles can enter the top 10; every edit still counts towards edits per minute and appears in the feed.
- **Vandalism is two-stage.** Free rules (blanking, large unexplained removals, anonymous editor, rude comment; reverts and bots excluded) pick candidates. Only those go to the LLM, together with the actual diff from the MediaWiki API. Spend scales with suspicious edits, not with stream volume.
- **The model must show its evidence.** It has to quote the damaging text from the diff, and a flag is published only if that quote really appears in the diff. Edits with no visible change are never sent to the model, and without a diff the model isn't asked at all (only strong rule matches are shown). This was added after llama3.2 flagged 2 of 2 live candidates at 100% confidence, one of them a change with no visible text.
- **Tuned for precision.** Wrongly accusing an editor on a client dashboard is worse than missing a borderline case: the prompt asks the model to be conservative, verdicts below 0.6 confidence aren't shown, and unsupported verdicts are rejected (counted in `/health`).
- **Bounded review queue that drops when full.** A flag 10 minutes late is useless on a live dashboard, so the queue drops new candidates rather than fall behind (the count is in `/health`).
- **AI only runs while someone is watching.** With no dashboard connected, the Pulse loop idles and edits aren't queued for review (`/health` shows `ai.paused_no_viewers`); ingestion and stats keep running. A tab that stays hidden for 3 minutes disconnects and reconnects when it's shown again, so a forgotten tab doesn't keep the model busy. I chose this over a manual "start" button: it saves the same calls without adding a step for the reviewer.
- **Separate LLM call budgets per feature** (16/min vandalism, 4/min Pulse). An early version shared one limit, and a burst of candidates used up the Pulse summary's calls. The budgets separate call *counts*; both features still share one client with two concurrent requests, so a slow model can delay Pulse while reviews are in flight.
- **Prompt-injection hygiene.** Edit comments and diffs are written by anyone, so they go into the prompt inside marked data blocks, and the system prompt tells the model never to follow instructions inside them.
- **Model output is validated** with Pydantic. Replies wrapped in code fences or extra prose (common with small local models) are still parsed; anything else counts as a failure and triggers the fallback.
- **Same-origin `/ws`** in dev (Vite proxy) and production (nginx), so the frontend has no environment-specific URLs.

## Assumptions

- "Edits" means `edit` and `new` (page creation) events. Log and categorise events are ignored.
- "Wikipedia" means the Wikipedia language editions (`*.wikipedia.org`). Wikidata, Commons, Wiktionary and other sister projects are dropped; `WIKIPEDIA_ONLY=false` brings them back.
- Bot edits are excluded from the stats (bots can dominate volume and drown out human trends) but still appear in the feed, labelled and dimmed. `INCLUDE_BOTS=true` changes this.
- IP editors and temporary accounts (`~YYYY-…`) are treated as anonymous. This is used as a signal for vandalism detection.
- Pulse summarises the whole stream (all wikis), not the currently filtered wiki: one summary on one timer keeps cost predictable.
- Vandalism review covers existing articles (namespace 0) only. New pages have no diff to quote, so they are only flagged by strong rule matches.

## Known limitations

- **Call limits are not a spending cap.** The budgets limit LLM calls per minute in this process. They reset on restart, count per process, and don't measure tokens; a dropped-field retry also makes a second request. A real spending limit belongs at the provider (account or project limits).
- **Vandalism flags are a review queue, not verdicts.** The evidence check proves the quoted text is in the diff, not that the model read it correctly. Detection accuracy isn't measured: there's no labelled set of edits, and the model's "confidence" is the model's own number, not a measured accuracy. The rule pre-filter is tuned on English comments and may behave differently on other languages.
- **The feed is sampled under load.** Each tick sends at most the 200 newest edits, and new clients get the last 50. If one wiki is very busy, a quiet wiki you've filtered to can miss feed rows during a burst; its counts and top pages stay correct because they come from the stats, not the feed.
- **One process, in memory.** Stats, flags and the Pulse summary live in memory: a restart starts from empty, and running several workers would give each its own ingester and AI budget. Run it as a single process (the Docker setup does).
- **Tested providers.** I ran it against Ollama (`llama3.2`) and Anthropic's OpenAI-compatible endpoint (`claude-haiku-5-5`). OpenAI and Gemini use the same API shape, but I haven't run them.
- **Starter files.** The brief's `LiveFeed.tsx`, `stream_client.py` and `sample_events.jsonl` were requested but had not arrived. `LiveSource` and `LiveFeed.tsx` are my own implementations, and `backend/data/sample_events.jsonl` is a small synthetic recording (it includes deliberate noise: a canary event, malformed lines, non-Wikipedia edits, blanking edits).

## What I'd do with more time

- Horizontal scaling: move fan-out to Redis pub/sub so several API instances share one ingester.
- Persist aggregates (e.g. per-minute counts in Postgres or TimescaleDB) for history beyond 5 minutes.
- Metrics (events/sec, lag, LLM latency and cost) and alerting on stream disconnects.
- Use Wikimedia's revert-risk model as an extra vandalism signal, and measure precision against edits that were later reverted.
- Cache verdicts per revision and let reviewers mark flags right or wrong to tune the threshold.
- Call Anthropic through its native Messages API (structured outputs) rather than the OpenAI-compatible layer, which Anthropic positions for evaluation.
- Virtualise the feed list for very high-volume wikis.
