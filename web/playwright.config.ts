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
    // Blocked by default, and this is a statement about the app rather than a
    // test convenience. A service worker answers `fetch` before the page's
    // network layer does, so a request it serves is invisible to `page.route`
    // -- every test here that injects a dataset would silently be testing the
    // real one instead. The worker is exercised deliberately in
    // `service-worker.spec.ts`, with `serviceWorkers: 'allow'`.
    serviceWorkers: 'block',
    channel: (process.env.TTB_BROWSER as 'chrome' | 'msedge' | undefined) ?? 'chrome',
    headless: true,
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command: 'npm run preview -- --port 4173 --strictPort',
    url: 'http://localhost:4173',
    // Never reused, including locally. `vite preview` builds its file map once
    // at startup, so a server left running across a rebuild serves the old one
    // -- and the symptom is not a clean failure. The suite took 7.4 minutes
    // instead of 43 seconds, the service-worker specs timed out, and
    // `/manifest.webmanifest` came back as `index.html` from the SPA fallback.
    // Every one of those looks like an application bug.
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
