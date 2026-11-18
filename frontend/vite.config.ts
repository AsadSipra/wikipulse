import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin in dev, matching production (nginx proxies the same paths).
    proxy: {
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
      '/api': backend,
      '/health': backend,
    },
  },
  // e2e/ holds Playwright specs, run separately with `npm run test:e2e`.
  test: { globals: true, environment: 'node', exclude: ['e2e/**', 'node_modules/**'] },
})
