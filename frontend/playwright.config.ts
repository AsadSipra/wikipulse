import { defineConfig } from '@playwright/test'

// End-to-end test against the real backend replaying the recorded sample, with
// AI turned off: deterministic data, no network to Wikipedia, no paid calls.
// Separate ports so it doesn't clash with a dev server you already have running.
const BACKEND_PORT = 8765
const FRONTEND_PORT = 5765

// Use the backend's virtualenv when there is one, otherwise python3 on PATH.
const python = '$( [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3 )'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://localhost:${FRONTEND_PORT}`,
    // Optional: use an installed Chrome instead of Playwright's.
    launchOptions: process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {},
  },
  webServer: [
    {
      command: `cd ../backend && WIKIPULSE_SOURCE=replay REPLAY_FILE=tests/data/synthetic_events.jsonl REPLAY_SPEED=5 AI_ENABLED=false ${python} -m uvicorn app.main:app --port ${BACKEND_PORT}`,
      url: `http://localhost:${BACKEND_PORT}/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `BACKEND_URL=http://localhost:${BACKEND_PORT} npx vite --port ${FRONTEND_PORT} --strictPort`,
      url: `http://localhost:${FRONTEND_PORT}`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
})
