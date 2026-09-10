import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'

/**
 * Testing Library waits one second by default for an element to appear. Every
 * route in this app is lazily imported, so a `findBy*` on a page has to cover a
 * dynamic import *and* Vite transforming that module the first time it is
 * asked for -- which on a busy machine takes longer than a second, and produces
 * a failure indistinguishable from a page that never rendered.
 *
 * `app.test.tsx` failed all eight of its cases when run on its own for exactly
 * this reason, and passed inside the full suite because other files had already
 * warmed the module graph. A suite whose result depends on what else ran is not
 * a suite anybody can act on.
 *
 * Ten seconds is not slow: nothing here waits the full timeout when it passes.
 */
configure({ asyncUtilTimeout: 10_000 })

// jsdom does not implement matchMedia; provide a minimal stub.
if (typeof window !== 'undefined' && !window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}