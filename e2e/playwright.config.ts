import { defineConfig } from '@playwright/test'

// End-to-end scenarios of the stages (docs/ACCEPTANCE.md), run in a browser
// against a deployed stack:
//
//   docker compose -f deploy/docker-compose.yml up -d --build
//   cd e2e && npm ci && npm run browsers && npm test
//
// TWIN_URL — the stack's address (default http://localhost:8090).
export default defineConfig({
  testDir: 'tests',
  globalSetup: './global-setup.ts',
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.TWIN_URL ?? 'http://localhost:8090',
    locale: 'ru-RU',
    trace: 'retain-on-failure',
  },
})
