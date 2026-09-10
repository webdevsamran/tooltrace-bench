import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
// `?raw` rather than `node:fs`: this file is type-checked by the app's tsconfig,
// which has no Node types, and Vite resolves a raw import in both the test run
// and the build.
import MANIFEST_TEXT from '../../public/manifest.webmanifest?raw'
import SW from '../../public/sw.js?raw'
import { OfflineBanner } from '../components'

/**
 * Offline support for a dashboard full of numbers has one hazard, and it is not
 * the caching: **a cached reliability figure looks exactly the same as a fresh
 * one**. A reviewer reading month-old numbers on a plane has no way to tell,
 * and "you are offline" alone leaves them to assume the data is current.
 *
 * So the banner names the date, the service worker serves data network-first,
 * and a dataset that is not cached returns an error rather than an empty
 * payload — an empty dataset renders as "no runs", which is a claim about the
 * data rather than about the network.
 */

const MANIFEST = JSON.parse(MANIFEST_TEXT)

describe('the offline banner', () => {
  it('says nothing at all when online', () => {
    const { container } = render(<OfflineBanner online={true} generatedAt="2026-09-10T00:00:00Z" />)
    expect(container.firstChild).toBeNull()
  })

  it('names the date the data on screen was generated', () => {
    render(<OfflineBanner online={false} generatedAt="2026-09-10T04:42:17Z" />)
    expect(screen.getByRole('status').textContent).toContain('2026-09-10')
  })

  it('says the age is unknown rather than implying the data is current', () => {
    render(<OfflineBanner online={false} />)
    expect(screen.getByRole('status').textContent).toContain('unknown age')
  })

  it('says nothing has been refreshed since', () => {
    render(<OfflineBanner online={false} generatedAt="2026-09-10T00:00:00Z" />)
    expect(screen.getByRole('status').textContent).toContain('nothing here has been refreshed')
  })
})

describe('the service worker', () => {
  it('serves data network-first so a working connection is not ignored', () => {
    // Cache-first here would serve month-old numbers to somebody online, and
    // they would look identical to fresh ones.
    expect(SW).toContain('Network-first')
    expect(SW).toMatch(/isData[\s\S]*fetch\(request\)/)
  })

  it('serves the shell cache-first, which is what makes it boot offline', () => {
    expect(SW).toContain('cache-first')
  })

  it('returns an error rather than an empty payload for uncached data', () => {
    // An empty dataset renders as "no runs" — a claim about the data rather
    // than about the network.
    expect(SW).toContain('504')
    expect(SW).toContain('not cached')
  })

  it('tags a cached response so the app can say the data may be stale', () => {
    expect(SW).toContain('X-ToolTrace-From-Cache')
  })

  it('installs the shell entry by entry rather than all-or-nothing', () => {
    // `cache.addAll(...)` rejects the whole install if any single request
    // fails, so one missing icon would leave the user with no offline support
    // at all. Matched as a call rather than as a word: the reason it is avoided
    // is written in a comment in that file, which names it.
    expect(SW).toContain('allSettled')
    expect(SW).not.toMatch(/\.addAll\(/)
  })

  it('leaves cross-origin requests alone', () => {
    expect(SW).toContain('url.origin !== self.location.origin')
  })

  it('resolves its scope relative to itself, so a project subpath works', () => {
    expect(SW).toContain("new URL('./', self.location)")
  })

  it('evicts caches from a previous version on activate', () => {
    expect(SW).toContain('caches.delete')
  })
})

describe('the web manifest', () => {
  it('uses relative paths so a GitHub Pages subpath works', () => {
    expect(MANIFEST.start_url).toBe('./')
    expect(MANIFEST.scope).toBe('./')
  })

  it('describes what offline actually means here', () => {
    expect(MANIFEST.description).toContain('cached')
    expect(MANIFEST.description).toContain('when those were generated')
  })
})
