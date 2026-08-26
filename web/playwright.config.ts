import { defineConfig } from '@playwright/test'

// E2E + accessibility smoke suite.
// Runs against the production build served by `vite preview`, using an
// already-installed browser via channel (no browser download needed):
//   - CI (ubuntu): Google Chrome is preinstalled -> channel "chrome"
//   - local Windows: Edge is preinstalled  -> set TTB_BROWSER=msedge
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'line' : 'list',
  use: {
    baseURL: 'http://localhost:4173',
    channel: (process.env.TTB_BROWSER as 'chrome' | 'msedge' | undefined) ?? 'chrome',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command: 'npm run preview -- --port 4173 --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
