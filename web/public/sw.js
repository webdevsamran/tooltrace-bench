/**
 * Offline support for inspecting bundles with no server.
 *
 * The dashboard is already static-first: it reads pre-generated JSON, so there
 * is nothing to talk to in the common case. What was missing is the last step —
 * a reviewer on a plane, or an auditor on a locked-down network, still gets a
 * blank page because the browser cannot fetch the app shell.
 *
 * ## The rule this file is built around
 *
 * **A cached dashboard must never present stale data as current.** That is the
 * whole hazard of making an evaluation dashboard work offline: numbers look
 * exactly the same whether they were fetched a second ago or a month ago, and a
 * reviewer reading a cached reliability figure has no way to tell. So:
 *
 * - The **shell** (HTML, JS, CSS) is cache-first. It changes only on deploy and
 *   a stale shell is harmless — the app re-renders whatever data it is given.
 * - The **data** is network-first. Online, you get today's numbers. Offline, you
 *   get the cached ones, and every dataset carries a `generated_at` the app
 *   displays. Cache-first here would silently serve month-old numbers to
 *   somebody with a perfectly good connection.
 *
 * A response served from cache is tagged with an `X-ToolTrace-From-Cache`
 * header so the app can say so rather than the user having to infer it from an
 * offline indicator that may itself be wrong.
 */

// Bumped on deploy so an old shell is evicted rather than lingering.
const SHELL_CACHE = 'tooltrace-shell-v1'
const DATA_CACHE = 'tooltrace-data-v1'

// Resolved relative to this file, so a project subpath (GitHub Pages) works
// without the base being baked in at build time.
const SCOPE = new URL('./', self.location).pathname

const SHELL = [SCOPE, `${SCOPE}index.html`, `${SCOPE}manifest.webmanifest`]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // Individually rather than addAll: addAll rejects the whole install if
      // any single request fails, which would mean one missing icon leaves the
      // user with no offline support at all.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

/** Tag a cached response so the app can say the data may be stale. */
function fromCache(response) {
  const headers = new Headers(response.headers)
  headers.set('X-ToolTrace-From-Cache', '1')
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  })
}

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  const isData = url.pathname.includes('/data/') || url.pathname.includes('/bundles/')

  if (isData) {
    // Network-first. Cache-first here would serve month-old reliability numbers
    // to someone with a working connection, and they would look identical to
    // fresh ones.
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            caches.open(DATA_CACHE).then((cache) => cache.put(request, copy))
          }
          return response
        })
        .catch(async () => {
          const cached = await caches.match(request)
          if (cached) return fromCache(cached)
          // A 504 rather than a fabricated empty payload: an empty dataset
          // renders as "no runs", which is a claim about the data rather than
          // about the network.
          return new Response(
            JSON.stringify({ error: 'offline, and this dataset is not cached' }),
            { status: 504, headers: { 'Content-Type': 'application/json' } },
          )
        }),
    )
    return
  }

  // Shell: cache-first, refreshed in the background. A stale shell is harmless.
  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone()
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy))
          }
          return response
        })
        .catch(() => cached)
      return cached ? fromCache(cached) : network
    }),
  )
})
