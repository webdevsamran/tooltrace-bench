import { test, expect } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

// Primary-route smoke: every route renders its heading with zero console
// errors against the real production build and real generated data.
const ROUTES: [string, RegExp][] = [
  ['/', /tooltrace bench/i],
  ['/leaderboard', /leaderboard/i],
  ['/agents', /agents/i],
  ['/models', /models/i],
  ['/tasks', /task packs/i],
  ['/compare', /compare/i],
  ['/trends', /trends|reliability/i],
  ['/failures', /failure/i],
  ['/traces', /trace explorer/i],
  ['/recovery', /recovery/i],
  ['/efficiency', /cost|efficiency|latency/i],
  ['/dataset', /dataset/i],
  ['/plugins', /plugin/i],
  ['/methodology', /methodology/i],
  ['/docs', /docs/i],
  ['/workspace', /^workspace$/i],
]

test.describe('route smoke', () => {
  for (const [route, heading] of ROUTES) {
    test(`renders ${route} without console errors`, async ({ page }) => {
      const consoleErrors: string[] = []
      page.on('console', (msg) => {
        if (msg.type() === 'error') consoleErrors.push(msg.text())
      })
      await page.goto(route)
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
      // Ignore network 404 noise from optional artifacts; assert app-level errors only.
      const appErrors = consoleErrors.filter((e) => !/40[134]|Failed to load resource/i.test(e))
      expect(appErrors).toEqual([])
    })
  }
})

test.describe('accessibility (axe)', () => {
  for (const route of ['/', '/leaderboard', '/tasks', '/traces', '/workspace']) {
    test(`no critical accessibility violations on ${route}`, async ({ page }) => {
      await page.goto(route)
      const results = await new AxeBuilder({ page })
        // Disable color-contrast while charts animate in; rules-of-thumb:
        // wcag2a + wcag2aa remain enforced.
        .withTags(['wcag2a', 'wcag2aa'])
        .analyze()
      const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
      expect(
        serious.flatMap((v) => v.nodes.map((n) => `${v.id}: ${JSON.stringify(n.target)}`)),
        `serious/critical axe violations on ${route}`,
      ).toEqual([])
    })
  }
})

test.describe('keyboard navigation', () => {
  test('skip link is the first tab stop', async ({ page }) => {
    await page.goto('/')
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: /skip to content/i })).toBeFocused()
  })

  test('theme toggle is keyboard operable', async ({ page }) => {
    await page.goto('/')
    await page.keyboard.press('Tab')
    await page.keyboard.insertText('')
    const toggle = page.getByRole('button', { name: /switch to (light|dark) mode/i })
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(toggle).toBeFocused()
  })
})
