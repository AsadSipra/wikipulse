# AI log

## How I work with AI

In my day-to-day work I use Claude Code inside a workspace I've set up for it. That workspace has three parts:

- **A rulebook:** coding conventions, git and PR rules, and a mandatory process for every ticket.
- **A knowledge base:** architecture notes, per-module notes and a growing list of gotchas, all indexed so the AI reads only what's relevant.
- **A work log:** one entry per finished task, with the root cause, the changes and how it was tested.

Each ticket follows the same phases, and the AI is never allowed to skip a human step:

1. **Investigate.** A research agent reads the code and data and reports facts, open questions and risks. It never guesses at a business rule; those questions come to me.
2. **Decide and plan.** I answer the open questions. A planning agent proposes the smallest correct design, and nothing is built until I approve the plan.
3. **Implement.** The approved plan is split into small, independent tasks, each done by a separate agent that follows the conventions and stops if the plan turns out to be wrong.
4. **Test.** A test-planning agent writes a concrete checklist from the real code, and I run it.
5. **Review.** I review the change myself. Then a stronger model, not the one that wrote the code, does a skeptical review. I verify the result before opening the PR.
6. **Learn.** Durable lessons go into the knowledge base. Every few tickets, a retrospective agent looks for repeated problems and suggests improvements to the process, and I decide which to adopt.

The effort scales with risk: a routine change gets a lighter pass, while anything touching money, auth or data migrations gets the full process.

For this take-home I used a lighter version of the same loop:
- I asked before assuming, and decided the open questions myself.
- Claude wrote changes straight into my project, where I reviewed them as they happened.
- I ran every test and command myself.
- An independent review pass checked the code.
- Lessons went into the README's decisions and into this log.

## Examples

I used Claude as a pair programmer: scaffolding, first drafts, debugging, and reviewing its output against tests and real data. Every change went through tests and a manual check before I kept it. Below are five examples, three of them times the AI was wrong.

### 1. Rolling-window expiry (AI was wrong)

- **Asked:** a 5-minute sliding window giving the top 10 pages and per-wiki counts.
- **Got:** per-second buckets, but on expiry the draft rebuilt the per-wiki totals by expanding every page counter. That is O(edits) work per expired second, and it left zero-count keys in memory.
- **Kept:** the per-second bucket design.
- **Changed:** each bucket keeps its own per-wiki counter, and a small `_subtract` helper removes keys exactly when they reach zero, so expiry costs only what that second contained.
- **Why:** the stream peaks at hundreds of edits a minute, so the window has to stay cheap and bounded. A test checks the totals are empty once the window has passed.

### 2. One shared rate limit starved the Pulse summary (AI was wrong)

- **Asked:** rate-limit LLM calls to protect the API budget.
- **Got:** one limiter of 20 calls a minute shared by the whole client.
- **What went wrong:** with replay running fast, vandalism reviews used the whole budget, and the Pulse card showed "AI unavailable" even though the model was fine.
- **Changed:**
  - Separate limits per feature (vandalism 16 a minute, Pulse 4), with a regression test.
  - Pulse keeps its last good summary (if under 3 minutes old) when one refresh fails.
  - Unreviewed rule matches stopped showing a fake 100% AI confidence. They now read "strong rule match, not reviewed by AI".
- **Why:** one noisy feature shouldn't silently break another, and the UI shouldn't claim the AI judged something it never saw.

### 3. Live data exposed what the unit tests couldn't

- **Asked:** for the features to be complete, and all tests passed against a fake model.
- **Did:** opened the dashboard on the live stream with a real model and read what it showed.
- **Found:**
  - Wikidata bulk edits filled the top 10 with item IDs (`Q141401630`), and Pulse called them "Wikipedia editors".
  - User sandboxes and noticeboards outranked articles.
  - The model flagged 2 of 2 vandalism candidates at 100% confidence, one with the reason "no textual change".
- **Changed:**
  - Only Wikipedia editions are ingested, and only articles can trend.
  - Edits with no visible change never reach the model.
  - The model must quote evidence, and a flag is shown only if that quote really appears in the diff. A regression test is built from the live failure.
- **Why:** "tests pass" proved the wiring, not the quality. Real data was the only way to see that.

### 4. The compatibility docs were wrong (AI was wrong)

- **Asked:** whether Anthropic's OpenAI-compatible endpoint would work with my client. The answer, based on the docs, was yes, with `response_format` ignored.
- **What happened:** every call failed, and the dashboard quietly fell back to the numbers-only summary. The log only said "400 Bad Request".
- **Changed:**
  - The provider's error message, with any key redacted, now appears in `/health`. That showed the endpoint rejects `response_format`, and then `temperature` too.
  - Both are now optional: if a provider rejects one with a 400 that names it, the client drops it and retries. Other errors are not retried. Tests use the exact error messages.
- **Why:** trust the error over the docs, and make failures visible without a terminal.

### 5. Controlling AI cost on a public demo

- **Asked:** I wanted a Start button so the hosted demo doesn't call the LLM around the clock.
- **Got:** a counter-proposal: pause AI on the server whenever no browser is connected, and disconnect a tab that has been hidden for 3 minutes.
- **Kept:** the server-side pause. Pulse and vandalism review stop when nobody is connected, and `/health` shows it.
- **Rejected:** the hidden-tab auto-disconnect. I replaced it with an explicit Start/Stop demo control, because a reviewer should see clearly when the demo is running rather than have it change behind their back.
- **Where the AI was right:** I then suggested removing the server-side pause, since the button seemed to cover it. The AI pointed out that the calls happen on the server, so without that check the button would only hide results while the spend continued. I kept it.
- **Accepted risk:** a tab left on Start keeps the AI running. This is documented in the README, with a per-demo time limit as the next step.

## What I did not use AI for

- **Product decisions:**
  - **Starting before the starter files arrived.** Only the brief came at first. Rather than wait, I built against the live stream and planned to merge the files later. When `sample_events.jsonl` arrived, it went in as the default replay with its traps handled.
  - **Asking few questions up front.** I kept the clarifying questions to the few that could block the work (missing files, an API key, how to share the result), and made reasonable assumptions for the rest, recorded in the README.
  - **A Start/Stop demo instead of automatic pausing.** A reviewer should always see clearly whether the demo is running.
  - **Accepting the left-running-demo risk.** It's documented, with a per-demo time limit as the next step, rather than adding more machinery to a demo.
  - **Switching from a local model to a hosted one** once the local model's quality wasn't good enough for vandalism verdicts.
  - **Capping cost on every AI call.** I asked for a max-tokens setting, so each reply is short and its cost is bounded.
  - **Hosting on AWS with credits I already had,** so the demo runs at no extra cost.
  - **Showing the product with a GIF of the live site** rather than a screenshot, because a live dashboard is best judged in motion.
- **Choosing which review findings to act on.** I decided which feedback was worth the time and which to leave.
- **Hands-on testing:**
  - running the app locally and on the live stream
  - reading the dashboard and judging when the output looked wrong (example 3 came from looking at the live dashboard, not from tests)
  - running every test and command on my own machine
- **Accounts and secrets.** I did the AWS setup and the credit and plan checks, managed GitHub, and kept API keys only in my local `.env`, never in prompts or the repo.
