import { defineConfig } from '@playwright/test'

// Trials of the copilot against the LIVE model set up on the stand (tools/README: docs/COPILOT.md § 7):
//
//   cd e2e && E2E_TAG=eval npx playwright test -c playwright.eval.config.ts
//
// Every scenario asks the copilot as a person would and checks the answer and the proposals by geometry and
// by text; the report lands in eval-results/<time>.md. The scenarios never apply what is proposed.
export default defineConfig({
  testDir: 'eval',
  globalSetup: './global-setup.ts',
  workers: 1,
  retries: 0,
  timeout: 20 * 60_000,
  reporter: [['list']],
  use: {
    baseURL: process.env.TWIN_URL ?? 'http://localhost:8090',
    locale: 'ru-RU',
  },
})
