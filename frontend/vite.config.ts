import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const backend = process.env.BACKEND_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin, like nginx in production.
    proxy: {
      '/ws': { target: backend.replace(/^http/, 'ws'), ws: true },
      '/api': backend,
      '/health': backend,
    },
  },
  // Playwright specs run separately.
  test: { globals: true, environment: 'node', exclude: ['e2e/**', 'node_modules/**'] },
})
