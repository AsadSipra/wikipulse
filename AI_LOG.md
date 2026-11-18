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

## 5. Shared LLM rate limit starved the Pulse summary: AI was wrong

- **Asked:** rate-limit LLM calls to protect the API key's spending limit.
- **Got:** one shared limiter of 20 calls a minute for the whole client.
- **What went wrong:** running the dashboard against a stand-in model at 3× replay speed, the vandalism reviews used the whole budget, and the Pulse card fell back to "AI unavailable" even though the model was fine.
- **Changed:** separate budgets per feature (`Budgeted` wrapper: 16/min vandalism, 4/min Pulse) with a regression test, and Pulse keeps a summary under 3 minutes old when one refresh fails. The UI also stopped labelling unreviewed rule matches "AI unavailable" with a fake 100% confidence; they now read "strong rule match, not reviewed by AI".

## 6. Testing against live data exposed what unit tests couldn't

- **Did:** opened the dashboard on the live stream with llama3.2 running locally and read what it actually showed.
- **Found:**
  - Wikidata bulk edits filled the entire top 10 with item IDs (`Q141401630`), and the Pulse summary described those batches as "Wikipedia editors".
  - On English Wikipedia, user sandboxes and noticeboards outranked articles.
  - The model flagged 2 of 2 vandalism candidates at 100% confidence, one with the reason "no textual change".
- **Changed:**
  - Ingest Wikipedia editions only, and let only articles trend.
  - Never send no-change edits to the model, and don't ask the model without a diff.
  - Require the model to quote evidence that must appear verbatim in the diff, with a regression test built from the live failure.
- **Lesson:** the tests passed against a fake model; the real model and real data needed their own look.

## 7. Switching to Claude: the compatibility docs were wrong

- **Asked:** whether Anthropic's OpenAI-compatible endpoint would work with the existing client. The answer, based on Anthropic's docs, was yes, and that `response_format` is ignored there.
- **What happened:** every call failed, and the dashboard silently fell back to the numbers-only summary.
  - First, the log only said "400 Bad Request". I added the provider's error message to `/health` (`llm_last_error`, never the key) so failures can be diagnosed without the terminal.
  - That showed the endpoint *rejects* `response_format: json_object`.
  - After that was fixed, the newer model rejected `temperature` too.
- **Changed:** `temperature` and `response_format` are treated as optional. If a provider rejects one with a 400 that names it, the client drops it for that provider and retries; other 400s are not retried. Covered by tests using the exact error messages seen.
- **Lesson:** trust the error message over the docs, and make errors visible.

## What I did not use AI for

- <!-- e.g. choosing the architecture and trade-offs, the window semantics (ingest vs event time), deciding what to test, the vandalism criteria -->
