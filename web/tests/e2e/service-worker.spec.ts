import { expect, test } from '@playwright/test'

/**
 * The offline path, exercised on purpose.
 *
 * Every other spec runs with `serviceWorkers: 'block'`, because a worker
 * answers `fetch` before the page's network layer and would make `page.route`
 * injection invisible. That is the right default and it would also leave this
 * feature entirely untested, which is the failure mode this repository keeps
 * finding in itself. So the worker gets its own file.
 */
test.use({ serviceWorkers: 'allow' })

test.describe('offline support', () => {
  test('the service worker registers and takes control', async ({ page }) => {
    await page.goto('/')
    const controlled = await page.evaluate(async () => {
      const registration = await navigator.serviceWorker.ready
      return Boolean(registration.active)
    })
    expect(controlled).toBe(true)
  })

  test('the app still boots on a second visit with the worker in control', async ({ page }) => {
    await page.goto('/')
    await page.evaluate(() => navigator.serviceWorker.ready)
    await page.reload()
    await expect(page.getByRole('heading', { name: /tooltrace bench/i })).toBeVisible()
  })

  test('the manifest is served and uses relative paths', async ({ page, baseURL }) => {
    const response = await page.request.get(`${baseURL}/manifest.webmanifest`)
    expect(response.ok()).toBe(true)
    const manifest = await response.json()
    // Absolute paths break the moment the site is served from a project
    // subpath, which is exactly how GitHub Pages serves it.
    expect(manifest.start_url).toBe('./')
    expect(manifest.scope).toBe('./')
  })

  test('data is fetched from the network when the network is there', async ({ page }) => {
    // Network-first for data is the load-bearing choice: cache-first would show
    // month-old reliability numbers to someone with a working connection, and
    // they would look identical to fresh ones.
    await page.goto('/')
    await page.evaluate(() => navigator.serviceWorker.ready)

    const requested: string[] = []
    page.on('request', (request) => {
      if (request.url().includes('/data/')) requested.push(request.url())
    })
    await page.goto('/leaderboard')
    await expect(page.getByRole('heading', { name: /leaderboard/i })).toBeVisible()
    expect(requested.length).toBeGreaterThan(0)
  })
})
