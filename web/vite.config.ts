/// <reference types="vitest" />
import { copyFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import type { Plugin, ResolvedConfig } from 'vite'

/**
 * The deploy base.
 *
 * This was `'./'`, with the comment "so the built site works from GitHub Pages
 * project subpaths". It does — for the root page only. Relative asset URLs
 * resolve against the *current route*, so `/results/<bundle>` asks for
 * `/results/assets/index-*.js`, gets a 404, and the application never boots.
 * Every nested route in this app — result detail, task detail, and the failure
 * clusters' link to the exact failing step — was therefore unopenable as a
 * link, in a browser tab, or after a refresh.
 *
 * An absolute base fixes that, and it has to be the real deploy prefix, so it
 * comes from the environment: `actions/configure-pages` knows the project
 * subpath and passes it in. Locally and in `vite preview` it is `/`.
 */
function normaliseBase(raw: string | undefined): string {
  const trimmed = (raw ?? '').replace(/^\/+|\/+$/g, '')
  return trimmed ? `/${trimmed}/` : '/'
}

/**
 * A static host has no router. Serving `index.html` for an unknown path is what
 * makes a client-side route reachable directly, and on GitHub Pages the hook
 * for that is `404.html`. Without it Pages answers its own 404 page and the
 * link is dead — an absolute base alone is not enough.
 */
function spaFallback(): Plugin {
  let config: ResolvedConfig
  return {
    name: 'ttb-spa-404-fallback',
    // After Vite's own html plugin has written index.html. Emitting during
    // generateBundle is too early: index.html is not in the bundle yet.
    enforce: 'post',
    configResolved(resolved) {
      config = resolved
    },
    writeBundle() {
      const out = resolve(config.root, config.build.outDir)
      const index = resolve(out, 'index.html')
      if (existsSync(index)) copyFileSync(index, resolve(out, '404.html'))
    },
  }
}

export default defineConfig({
  plugins: [react(), spaFallback()],
  base: normaliseBase(process.env.TTB_BASE),
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.ts',
    // Playwright e2e specs live outside vitest.
    exclude: ['tests/e2e/**', 'node_modules/**', 'dist/**'],
  },
})
