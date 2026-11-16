# AI log

<!--
DRAFT. Rewrite each entry in your own words before submitting, and keep only
what you actually did and agree with. Add the AI-feature work as it happens.
They will ask about these entries in the interview.
-->

Tool used: Claude (as a pair-programmer: scaffolding, first drafts, and reviewing its own output against tests).

## 1. Rolling-window expiry: AI was wrong

- **Asked:** a sliding 5-minute window with top-10 pages and per-wiki counts.
- **Got:** a first draft that, on expiry, rebuilt the per-wiki totals by expanding each page counter into individual items. That costs O(number of edits) per expired bucket, and it relied on a periodic `+Counter` clean-up that left zero-count keys in memory between runs.
- **Changed:** each bucket now keeps its own per-wiki counter, and a small `_subtract` helper deletes keys exactly when they reach zero. I added a test asserting the totals are empty after the window passes.

## 2. Top-pages links

- **Got:** page URLs built by searching the last 50 feed edits for that wiki's hostname.
- **Rejected:** on a quiet wiki, a page can stay in the top 10 longer than its edit stays in the last 50, so the link would silently become `null`.
- **Changed:** a small `wiki → host` map, updated on every edit (around 1,000 entries at most).

## 3. Chart library

- **Suggested:** adding a charting library for the edits-per-minute chart.
- **Rejected:** one line series doesn't need it. A ~25-line SVG component keeps the bundle small and has no dependency to explain.

## 4. Debugging a "broken" WebSocket

- A headless Chrome screenshot showed the dashboard stuck on "Reconnecting". Rather than change the code, we tested the socket directly (both the backend and the Vite proxy returned `init` messages). The cause was the screenshot tool's virtual-time mode, not the app. Lesson: confirm the bug exists before fixing it.

## What I did not use AI for

- <!-- e.g. choosing the architecture and trade-offs, the window semantics (ingest vs event time), deciding what to test, the vandalism criteria -->
