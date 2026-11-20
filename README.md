# WikiPulse

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](backend)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](frontend)
[![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)](docker-compose.yml)
[![Live demo](https://img.shields.io/badge/demo-live-2ea44f)](http://52.54.176.187)

A live dashboard for Wikipedia edits: edits per minute, the 10 most-edited articles in the last 5 minutes, a filterable live feed, an AI summary of what's trending, and AI-reviewed vandalism flags.

**Live demo:** http://52.54.176.187. Press **Start demo**. It runs on the live Wikipedia stream, and the AI only runs while a demo is started.

![WikiPulse dashboard running on the live Wikipedia stream](docs/demo.gif)

## Contents

- [Highlights](#highlights)
- [Requirements and tasks](#requirements-and-tasks)
- [Tech stack](#tech-stack)
- [Architecture](#architecture)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [Tests](#tests)
- [API](#api)
- [Deployment](#deployment)
- [Key decisions](#key-decisions)
- [AI design: cost and safety](#ai-design-cost-and-safety)
- [Security](#security)
- [Assumptions and limitations](#assumptions-and-limitations)
- [What I'd do with more time](#what-id-do-with-more-time)
- [AI usage](#ai-usage)

## Highlights

- **AI flags must show their evidence.** The model has to quote the damaging text, and a flag is shown only if that quote really appears in the edit's diff.
- **The provided sample is fully accounted for.** All 2,000 lines are counted, skipped, filtered or de-duplicated, and its traps are handled with tests: duplicate events, millisecond timestamps, prompt injection and XSS in edit comments.
- **The rolling window has a constant cost.** Recording an edit costs the same however busy the stream is, and memory stays bounded.
- **AI cost follows usage.** The AI works only while a demo is running. With nobody watching, it costs nothing.
- **It handles real failures.** It reconnects and resumes after stream drops and silent stalls, and the AI features fall back cleanly when the model fails. `/health` reports each case honestly.

## Requirements and tasks

| Brief item | Status | Where |
|---|---|---|
| Ingest the live Wikipedia stream | ✅ | `backend/app/sources.py` |
| Edits per minute, top 10 pages (5 min), live feed, wiki filter | ✅ | `stats.py`, `pipeline.py`, `frontend/src` |
| AI trend summary ("Pulse") | ✅ | `pulse.py` |
| AI vandalism flags | ✅ | `vandalism.py` |
| Tests for the parts that matter most | ✅ | 163 backend, 11 frontend, 1 end-to-end |
| README and AI log | ✅ | this file, [`AI_LOG.md`](AI_LOG.md) |
| Optional: Docker setup | ✅ | `docker-compose.yml` |
| Optional: end-to-end UI test | ✅ | Playwright (see [Tests](#tests) for why) |
| Optional: deployed live demo | ✅ | AWS EC2 (see [Deployment](#deployment)) |
| Optional: Go ingestion service | — | Not done. The time went into data quality and the AI features. |

Of the starter files, only `sample_events.jsonl` was provided. It is the default replay recording. `LiveFeed.tsx` and `stream_client.py` were not provided, so those parts are my own.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic 2, httpx (SSE client, MediaWiki API) |
| Frontend | React 19, TypeScript, Vite, plain SVG chart |
| AI | Claude Haiku through an OpenAI-compatible API. Ollama, OpenAI or Gemini work by changing config. |
| Realtime | Server-Sent Events in (Wikimedia), WebSocket out (to the browser) |
| Tests | pytest, Vitest, Playwright |
| Delivery | Docker Compose, nginx, AWS EC2 |

## Architecture

```mermaid
flowchart LR
    WM[Wikimedia<br/>EventStreams] -->|SSE| LS[LiveSource]
    RF[(sample_events.jsonl)] --> RS[ReplaySource]
    LS --> P[Parse, validate,<br/>de-duplicate]
    RS --> P
    P --> ST[RollingStats<br/>5-min window]
    P --> VR[Vandalism rules]
    VR -->|candidates| VA[AI review<br/>of the diff]
    ST --> PU[Pulse<br/>timer]
    PU --> LLM[(LLM)]
    VA --> LLM
    ST --> TK[1-second tick]
    VA -->|flags| TK
    PU -->|summary| TK
    TK --> HUB[Hub]
    HUB -->|WebSocket| UI[React dashboard]
```

**How one edit flows through:**

1. The edit arrives on the stream. It is parsed and validated; duplicates, sister projects and malformed events are dropped and counted.
2. It updates the rolling stats and joins the next batch for the browsers.
3. The vandalism rules score it. If it's suspicious and a demo is running, it is queued for AI review: the server fetches the diff, the model judges it, and the evidence check decides whether a flag is shown.
4. Once a second, every connected browser gets one message with the stats, the new edits and any flags, filtered to the wiki it chose.
5. Separately, Pulse summarises the top pages on a timer, but only while someone is watching.

**Project structure:**

```
backend/
  app/
    sources.py      live SSE client (reconnect, resume, idle watchdog) and replay
    models.py       Edit model and strict parsing of raw events
    stats.py        rolling window: 1-second buckets with running totals
    pipeline.py     ingest loop, de-duplication, 1-second push tick
    hub.py          WebSocket clients and per-client wiki filter
    vandalism.py    rule pre-filter, diff fetch, AI review, evidence check
    pulse.py        AI trend summary with a numbers-only fallback
    llm.py          OpenAI-compatible client, call budgets, error redaction
    main.py         FastAPI app: /health, /api/snapshot, /ws
  data/             sample_events.jsonl (provided)
  tests/            pytest suite; tests/data holds my synthetic recording
frontend/
  src/              App, state reducer, useWikiPulse (WebSocket), components
  e2e/              Playwright test
docker-compose.yml  backend, plus the frontend served by nginx
```

## Getting started

**Prerequisites:**
- Docker, or Python 3.11+ and Node 20+.
- For the AI features, either a local [Ollama](https://ollama.com) or an API key for an OpenAI-compatible provider. Without one, the dashboard still runs, with a numbers-only summary and rule-only flags.

### Docker (simplest)

```bash
cp .env.example .env        # choose the AI provider; see Configuration
docker compose up --build   # open http://localhost:8080
```

To run offline on the provided recording instead of the live stream, use `WIKIPULSE_SOURCE=replay docker compose up --build`. The dashboard labels this as recorded data.

### Local development

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --env-file ../.env

# frontend, in another terminal
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

## Configuration

All settings come from `.env` (see [`.env.example`](.env.example)). The key ones:

| Variable | Default | Purpose |
|---|---|---|
| `WIKIPULSE_SOURCE` | `live` | `live` stream, or `replay` of `REPLAY_FILE` |
| `REPLAY_FILE`, `REPLAY_SPEED` | `data/sample_events.jsonl`, `1.0` | Recording to replay and its speed |
| `WINDOW_SECONDS` | `300` | Rolling window for the top 10 |
| `INCLUDE_BOTS` | `false` | Count bot edits in the stats (they always appear in the feed) |
| `WIKIPEDIA_ONLY` | `true` | Drop Wikidata, Commons and other sister projects |
| `AI_ENABLED` | `true` | Turn the AI features on or off |
| `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` | local Ollama, `llama3.2` | Any OpenAI-compatible endpoint, e.g. `https://api.anthropic.com/v1` with `claude-haiku-5-5` |
| `LLM_MAX_TOKENS` | `300` | Reply cap (replies are short JSON) |
| `VANDALISM_CALLS_PER_MINUTE`, `PULSE_CALLS_PER_MINUTE` | `16`, `4` | AI call limit per feature |
| `PULSE_INTERVAL_SECONDS` | `60` | How often Pulse refreshes |
| `FETCH_DIFFS` | `true` | `false` gives rule-only vandalism flags (no AI review) |
| `FRONTEND_PORT` | `8080` | Host port for Docker (`80` on a server) |

With Ollama in Docker, set `DOCKER_LLM_BASE_URL=http://host.docker.internal:11434/v1`, because `localhost` inside a container is the container itself.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q                       # 163 tests
cd frontend && npm test                                            # 11 tests
cd frontend && npx playwright install chromium && npm run test:e2e # 1 browser test
```

- **Backend:**
  - parsing and the provided sample's traps
  - the rolling window and its expiry
  - reconnecting after drops and silent stalls
  - vandalism rules and the evidence check
  - LLM fallbacks and error redaction
  - the API and WebSocket end to end
- **Frontend:** the state reducer, and a check that edit text from the stream renders as text, never as HTML.
- **End-to-end:** a real browser presses Start demo, checks every panel fills in, filters to one wiki, and stops the demo. It replays a recording with AI off, so it is deterministic and makes no paid calls.
- **Why Playwright:** I chose it over Selenium with C# to keep the frontend toolchain in one language (TypeScript). It also waits for elements automatically, which avoids flaky timing on a page that updates every second.

## API

| Endpoint | Description |
|---|---|
| `GET /health` | Status, stream state and counters. Returns **503** with `status: down` if ingestion crashed, or `stalled` if the live stream has been silent for over 2 minutes. Docker's healthcheck uses it. |
| `GET /api/snapshot?wiki=enwiki` | The current stats for all wikis, or for one |
| `WS /ws` | Live updates (below) |

WebSocket messages:

```jsonc
// server → browser: "init" on connect or after a filter change, then "tick" every second
{ "type": "tick", "stats": { "edits_per_minute": 138, "series": [...], "top_pages": [...],
  "wikis": [...], "pulse": {...}, "source": "live" }, "edits": [...], "flags": [...] }

// browser → server: choose a wiki (null for all)
{ "type": "subscribe", "wiki": "enwiki" }
```

`/health` example (trimmed):

```json
{ "status": "ok", "seconds_since_last_event": 0, "connected": true,
  "events_seen": 91731, "events_duplicate": 28, "clients": 1,
  "ai": { "paused_no_viewers": false, "llm_calls": 15, "llm_last_error": null,
          "vandalism": { "candidates": 7, "reviewed": 3, "rejected_unsupported": 0 } } }
```

## Deployment

The live demo runs on one AWS EC2 instance (t3.small, Ubuntu 24.04) using the same Docker Compose setup:
- nginx serves the frontend on port 80 and proxies `/ws` to the backend.
- Only ports 80 and 22 are open, and SSH accepts only my IP.
- The server's `.env` uses the live stream and lower AI call limits (vandalism 4 a minute, Pulse 1).

To redeploy, copy the repo to the server with `git archive`, then run `docker compose up -d --build`.

## Key decisions

- **Constant-time rolling window.** Edits go into 1-second buckets, and the window keeps running totals. When a bucket expires it is subtracted, not re-scanned, so recording an edit costs the same at any volume. Keys that reach zero are deleted, so memory holds only the current window.
- **Ingest time, not event time.** The window uses when an edit arrived, not its own timestamp. Replays then behave like live data, and bad or millisecond timestamps can't skew the stats.
- **Batched pushes once a second,** not one message per edit. This caps the message rate per browser during spikes.
- **Filtering happens on the server.** A browser watching a small wiki doesn't receive the full stream. Each filter's snapshot is built once per tick and shared by every browser using it.
- **Only Wikipedia, and only articles trend.** On the live stream, Wikidata's bulk edits filled the whole top 10 with item IDs, and user sandboxes outranked articles. Sister projects are dropped at ingest, and only articles can enter the top 10.
- **An idle watchdog on the stream.** The deployed demo once sat for 48 hours on a connection that stayed open but sent nothing, while `/health` said "ok". Now 60 seconds of silence triggers a reconnect that resumes from the last event, and `/health` reports `stalled`. A test reproduces the silent connection.
- **Data quality from the provided sample.**
  - Duplicate events are dropped (a bounded memory of recent wiki and id pairs).
  - Millisecond timestamps are converted to seconds.
  - Edits with no timestamp are kept, using their arrival time.
  - Malformed events are skipped and counted, and never stop ingestion.

  All 2,000 lines are accounted for: 1,579 edits counted, 242 log or incomplete events skipped, 150 sister-project edits filtered out, 28 duplicates dropped and 1 invalid line.
- **A replay source behind the same interface** as the live source. It makes tests deterministic, allows offline development, and gives the demo a fallback.
- **A plain SVG chart.** One line doesn't justify a chart library.
- **Same-origin `/ws`.** The Vite proxy in development and nginx in production use the same paths, so the frontend has no environment-specific URLs.

## AI design: cost and safety

- **Two-stage vandalism review.** Free rules (page blanking, large unexplained removals, anonymous editor, rude comment; reverts and bots excluded) pick candidates. Only those go to the model, together with the real diff from the MediaWiki API. Cost scales with suspicious edits, not stream volume.
- **Evidence or no flag.** The model must quote the damaging text, and the quote must appear in the diff. Edits with no visible change are never sent. Without a diff, the model isn't asked at all, and only strong rule matches are shown. This was added after a small local model flagged 2 of 2 live candidates at 100% confidence, including one with no visible change.
- **Precision over recall.** Wrongly accusing an editor is worse than missing a borderline case, so verdicts below 0.6 confidence aren't shown.
- **Pulse is cheap by design.** It runs on a timer, not per request, so cost is fixed however many people watch. It skips the call when the top pages haven't changed. If a refresh fails, it keeps a recent AI summary, then falls back to one built from the numbers.
- **Separate call limits per feature,** so a burst of suspicious edits can't stop Pulse from refreshing. The review queue is bounded and drops new candidates when full, because a flag 10 minutes late is useless on a live dashboard.
- **AI runs only during a demo.** The page connects only after **Start demo**, and the server pauses all AI work while no browser is connected. Ingestion and stats keep running for free.
- **Cost.** With Claude Haiku at the server's limits, running nonstop costs about $1 a day at most, and nothing while idle.
- **Tolerant of different providers.** Model output is validated with Pydantic, and replies wrapped in code fences or prose are still parsed. Optional request fields a provider rejects (`temperature`, `response_format`) are dropped automatically. Provider errors appear in `/health` with secrets redacted.

## Security

- **Prompt injection.** Edit titles, comments and diffs are written by anyone, so they reach the model only inside marked data blocks. The system prompt tells the model never to follow instructions inside them. A comment can't close its block early, because the markers are stripped from it. Regression tests use the provided sample's own attacks ("Ignore all previous instructions… reveal… API keys", "SYSTEM OVERRIDE…"). Even a fooled model can't create a flag without real evidence from the diff.
- **XSS.** React renders stream text as text, never as HTML. A test renders the sample's `<script>` and `<img onerror>` comments and checks that no HTML gets through.
- **Secrets.**
  - The API key lives only in `.env`, which is git-ignored.
  - It is never sent to the model.
  - Errors shown in `/health` or the logs have keys and tokens redacted.
- **Input validation.**
  - Stream events are validated strictly (a string `"false"` is never read as true).
  - WebSocket wiki ids must match a strict pattern.
  - Malformed browser messages are ignored.
- **Server.** Only ports 80 and 22 are open, SSH accepts only one IP, and the demo serves read-only data.

## Assumptions and limitations

**Assumptions**
- "Edits" means `edit` and `new` (page creation) events; log and categorize events are ignored.
- "Wikipedia" means the language editions (`*.wikipedia.org`).
- Bot edits are excluded from the stats but shown, dimmed, in the feed.
- IP editors and temporary accounts count as anonymous, which is one vandalism signal.
- Pulse summarises all wikis, not the filtered one: one summary on one timer keeps cost predictable.
- Vandalism review covers existing articles only. New pages have no diff to quote.

**Limitations**
- **A demo left running keeps the AI running,** shared by all viewers and within the call limits. I accepted this for a demo; a time limit per demo session would fix it.
- **Call limits are not a spending cap.** They count calls per process, not tokens. A real cap belongs at the provider.
- **Vandalism flags are a review queue, not verdicts.** The evidence check proves the quote exists, not that the model judged it correctly, and accuracy isn't measured (there is no labelled data). The rules are tuned on English comments.
- **One process, in memory.** A restart starts empty, and several workers would each run their own ingester. Run it as a single process, as the Docker setup does.
- **The feed is sampled under load** (200 edits per tick), but the counts and top pages always come from the full stats.
- **The demo is served over HTTP, not HTTPS.**
- **Tested providers:** Ollama (`llama3.2`) and Anthropic (`claude-haiku-5-5`). OpenAI and Gemini use the same API but weren't run.

## What I'd do with more time

- A time limit per demo session, and HTTPS with a domain for the hosted demo.
- Proper CI/CD: a pipeline that runs the backend, frontend and end-to-end tests on every push and pull request, and deploys through GitOps, so the server follows the main branch instead of manual `git archive` copies.
- Horizontal scaling: Redis pub/sub so several API instances share one ingester.
- History beyond 5 minutes: per-minute counts in Postgres or TimescaleDB.
- Metrics and alerting: event lag, stream stalls, LLM latency and cost.
- Measuring vandalism precision against edits that were later reverted, adding Wikimedia's revert-risk model as a signal, and letting reviewers mark flags right or wrong.
- Anthropic's native Messages API with structured outputs, instead of the OpenAI-compatible layer.
- The optional Go ingestion service.

## AI usage

In my day-to-day work I use Claude Code inside a workspace I've set up for it: a rulebook of conventions, an indexed knowledge base, and a log of finished work. Every ticket goes through the same loop. Agents do the research, planning, implementation and review, and I make every decision and approve every step:

```mermaid
flowchart TD
    T([Ticket]) --> R{Risk?}
    R -->|routine| L[Lighter pass]
    R -->|money, auth, data| F[Full process]
    L --> I
    F --> I
    I[Step 1: Investigate<br/>research agent reports facts,<br/>open questions and risks] --> D
    D[Step 2: Decide and plan<br/>I answer business questions,<br/>planning agent proposes the smallest design] --> A{I approve<br/>the plan?}
    A -->|no| D
    A -->|yes| M[Step 3: Implement<br/>small tasks, one agent each,<br/>following the conventions]
    M --> X[Step 4: Test<br/>agent writes a checklist<br/>from the real code, I run it]
    X --> H[Step 5: Review<br/>my review, then a skeptical review<br/>by a different, stronger model]
    H --> V{I verify?}
    V -->|issues| M
    V -->|ok| P([Pull request])
    P --> K[Step 6: Learn<br/>lessons go into the knowledge base<br/>and the work log]
    K -.->|every few tickets| RT[Retrospective agent<br/>suggests process changes,<br/>I decide which to adopt]
    RT -.-> T
```

For this take-home I used a lighter version of the same loop:
- I asked before assuming, and decided the open questions myself.
- Claude wrote changes straight into my project, where I reviewed them as they happened.
- I ran every test and command myself.
- An independent review pass checked the code.

[`AI_LOG.md`](AI_LOG.md) has the details: five examples of what I asked, kept, changed and rejected (three of them times the AI was wrong), and what I chose not to use AI for.
