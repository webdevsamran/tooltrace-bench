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
  ['/compare/runs', /compare two runs/i],
  ['/trends', /trends|reliability/i],
  ['/failures', /failure/i],
  ['/traces', /trace explorer/i],
  ['/security', /security posture/i],
  ['/evidence', /evidence/i],
  ['/recovery', /recovery/i],
  ['/efficiency', /cost|efficiency|latency/i],
  ['/frontier', /frontier/i],
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
  for (const route of ['/', '/leaderboard', '/tasks', '/traces', '/failures', '/security', '/evidence', '/frontier', '/compare/runs', '/workspace']) {
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

/**
 * The brush, against a frontier that exists.
 *
 * The published dataset has exactly one agent -- `scripted`, which has no model
 * and therefore no cost -- so `/frontier` renders its empty state and the chart
 * never draws. That is the page behaving correctly, and it means the shipped
 * data cannot exercise the brush. Inventing multi-agent priced results to put
 * on the real site would be the dishonesty this whole project is built against.
 *
 * So the data is intercepted, exactly as the failure-cluster suite above does:
 * real component, real browser, real keyboard, synthetic input that is
 * obviously synthetic and never leaves this file.
 */
/**
 * The live console, reached the way a reader without a server reaches it.
 *
 * Every workspace page renders inside a `ServerGate`, so the route smoke above
 * would only ever see the connect form -- which is why no gated page is in that
 * list. Clicking through to the labelled DEMO preview exercises the real page
 * instead, with no SSE attached, which is also the state most visitors will see
 * it in.
 */
/**
 * The quality bar the spec sets, at the sizes nobody develops at.
 *
 * Every other case in this file runs at 1280x800, which is the one width a
 * layout is never broken at. The spec says "responsive from 360px to
 * ultrawide" and "no layout shift", and both are measurable rather than
 * matters of taste, so they are measured.
 */
test.describe('quality bar', () => {
  // A 360px-wide viewport is a small phone -- the narrow end of the range the
  // spec names, and the width where a fixed-width table or an un-wrapped
  // toolbar pushes the whole page sideways.
  const NARROW = { width: 360, height: 740 }

  for (const route of ['/', '/leaderboard', '/traces', '/frontier', '/failures']) {
    test(`${route} does not scroll sideways at 360px`, async ({ page }) => {
      await page.setViewportSize(NARROW)
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      // `documentElement` rather than `body`: the body can be narrower than the
      // content that overflows it, which is exactly how this goes unnoticed.
      //
      // The offenders come back with the number. A bare "overflows by 223px"
      // sends the next person to write three throwaway diagnostics, which is
      // what it cost the first time.
      const { overflow, offenders } = await page.evaluate(() => {
        const root = document.documentElement
        const limit = root.clientWidth
        const names: string[] = []
        for (const node of Array.from(document.body.querySelectorAll('*'))) {
          const rect = node.getBoundingClientRect()
          if (rect.right <= limit + 1) continue
          // An ancestor that scrolls is doing its job: the element is clipped
          // and reachable, and only an unclipped one moves the page.
          let clipped = false
          for (let a: Element | null = node.parentElement; a; a = a.parentElement) {
            const ox = getComputedStyle(a).overflowX
            if (ox === 'auto' || ox === 'scroll' || ox === 'hidden') { clipped = true; break }
          }
          if (clipped) continue
          const cls =
            typeof node.className === 'string' && node.className
              ? `.${node.className.trim().split(/\s+/).join('.')}`
              : ''
          names.push(`${node.tagName.toLowerCase()}${cls}`)
        }
        return { overflow: root.scrollWidth - limit, offenders: [...new Set(names)].slice(0, 8) }
      })
      // One pixel of slack for sub-pixel rounding at fractional device ratios.
      expect(
        overflow,
        `${route} overflows by ${overflow}px at 360px; unclipped: ${offenders.join(', ') || '(none found)'}`,
      ).toBeLessThanOrEqual(1)
    })
  }

  test('wide content scrolls inside its own container, not the page', async ({ page }) => {
    // The fix for an overflowing table is a scroll container around it, not a
    // narrower table: the data has the width it has.
    await page.setViewportSize(NARROW)
    await page.goto('/leaderboard')
    await page.waitForLoadState('networkidle')
    const wide = await page.evaluate(() => {
      const scrollable = (el: Element | null): boolean => {
        // The container can be the element itself -- a `<pre>` with
        // `overflow-x: auto` scrolls its own content, and an earlier version of
        // this check only looked at the parent and reported it as an offender.
        for (let node = el; node; node = node.parentElement) {
          const overflow = getComputedStyle(node).overflowX
          if (overflow === 'auto' || overflow === 'scroll') return true
        }
        return false
      }
      const offenders: string[] = []
      for (const el of Array.from(document.querySelectorAll('table, pre, .console-log'))) {
        const parent = el.parentElement
        if (!parent) continue
        if (el.scrollWidth > parent.clientWidth + 1 && !scrollable(el)) {
          offenders.push(el.tagName.toLowerCase() + (el.className ? `.${el.className}` : ''))
        }
      }
      return offenders
    })
    expect(wide).toEqual([])
  })

  for (const route of ['/', '/leaderboard', '/traces']) {
    test(`${route} settles without shifting its layout`, async ({ page }) => {
      // Cumulative Layout Shift, measured rather than asserted by eye. 0.1 is
      // the "good" threshold every tool uses; anything above it is content
      // moving under a reader's finger after they started reading.
      await page.goto(route)
      await page.evaluate(() => {
        const w = window as Window & { __cls?: number }
        w.__cls = 0
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            const shift = entry as PerformanceEntry & { value: number; hadRecentInput: boolean }
            // Shifts within 500ms of an interaction are expected and excluded
            // by the metric's own definition.
            if (!shift.hadRecentInput) w.__cls = (w.__cls ?? 0) + shift.value
          }
        }).observe({ type: 'layout-shift', buffered: true })
      })
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(500)
      const cls = await page.evaluate(() => (window as Window & { __cls?: number }).__cls ?? 0)
      expect(cls, `${route} shifted by ${cls}`).toBeLessThan(0.1)
    })
  }
})

test.describe('live console', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/workspace/console')
    await page.getByRole('button', { name: /preview with demo data/i }).click()
  })

  test('renders behind the gate, with its controls', async ({ page }) => {
    await expect(page.getByRole('heading', { name: /live console/i })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Pause' })).toBeVisible()
    await expect(page.getByLabel('Filter events')).toBeVisible()
  })

  test('does not announce every frame unless the reader asks', async ({ page }) => {
    // A live region on a running sweep reads every event aloud and interrupts
    // itself. Off by default is the accessible choice, not the lazy one.
    const announce = page.getByRole('checkbox', { name: /announce new events/i })
    await expect(announce).not.toBeChecked()
  })

  test('says what the buffer holds even when it holds nothing', async ({ page }) => {
    await expect(page.getByRole('status', { name: 'Console buffer' })).toContainText(
      '0 events shown.',
    )
  })

  test('offers an empty state rather than a blank panel', async ({ page }) => {
    await expect(page.getByText(/no events yet/i)).toBeVisible()
  })

  test('no critical accessibility violations', async ({ page }) => {
    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => ['critical', 'serious'].includes(v.impact ?? ''))
    expect(serious.map((v) => `${v.id} on ${v.nodes.length} node(s)`)).toEqual([])
  })
})

test.describe('chart brushing', () => {
  const FRONTIER = {
    points: [
      { agent: 'alpha', success_rate: 0.9, cost_per_resolved_task: 0.4, total_cost: 4, priced_runs: 10, runs: 10 },
      { agent: 'beta', success_rate: 0.7, cost_per_resolved_task: 0.1, total_cost: 1, priced_runs: 10, runs: 10 },
      { agent: 'gamma', success_rate: 0.5, cost_per_resolved_task: 0.9, total_cost: 9, priced_runs: 10, runs: 10 },
    ],
    frontier: ['alpha', 'beta'],
    unpriced: [],
    statement: 'two agents on the frontier, one dominated',
  }

  test.beforeEach(async ({ page }) => {
    await page.route('**/data/pareto.json', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FRONTIER) }),
    )
  })

  test('is reachable and usable without a mouse', async ({ page }) => {
    // The justification for building the brush as four number inputs *plus* a
    // drag rather than a drag alone. `brush.test.tsx` proves the controls work;
    // only a real browser proves they are reachable on the real page -- an
    // input behind an overflow clip, or with a negative tabindex, passes every
    // unit test and is still unreachable.
    await page.goto('/frontier')
    const min = page.getByLabel('Min cost')
    await min.focus()
    await expect(min).toBeFocused()

    // Tab order walks the four edges and then the clear button.
    for (const label of ['Max cost', 'Min accuracy', 'Max accuracy']) {
      await page.keyboard.press('Tab')
      await expect(page.getByLabel(label)).toBeFocused()
    }
    await page.keyboard.press('Tab')
    await expect(page.getByRole('button', { name: 'Clear range' })).toBeFocused()
  })

  test('narrows the reported set rather than hiding points', async ({ page }) => {
    // The rule the brush exists to obey: a reader looking at a subset must be
    // told it is a subset. Silently dropping the other points is the same
    // defect as reading a shard's pass rate as the sweep's.
    await page.goto('/frontier')
    await expect(page.getByRole('status', { name: 'Selected range' })).toContainText('No range selected; showing all 3.')

    await page.getByLabel('Min cost').fill('0.3')
    await expect(page.getByRole('status', { name: 'Selected range' })).toContainText('2 of 3 in the selected range.')
    await expect(page.getByRole('status', { name: 'Selected range' })).toContainText('alpha')

    // Every agent is still drawn: the range is an annotation, not a filter that
    // removes evidence from the chart.
    await expect(page.getByRole('button', { name: /^gamma:/ })).toBeVisible()
  })

  test('clearing returns to the whole set', async ({ page }) => {
    await page.goto('/frontier')
    await page.getByLabel('Min cost').fill('0.3')
    await expect(page.getByRole('status', { name: 'Selected range' })).toContainText('2 of 3')
    await page.getByRole('button', { name: 'Clear range' }).click()
    await expect(page.getByRole('status', { name: 'Selected range' })).toContainText('showing all 3')
  })

  test('no critical accessibility violations with a brush on screen', async ({ page }) => {
    await page.goto('/frontier')
    await page.getByLabel('Min cost').fill('0.3')
    const results = await new AxeBuilder({ page }).analyze()
    const serious = results.violations.filter((v) => ['critical', 'serious'].includes(v.impact ?? ''))
    expect(serious.map((v) => `${v.id} on ${v.nodes.length} node(s)`)).toEqual([])
  })
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
    const toggle = page.getByRole('button', { name: /^theme:/i })
    await toggle.focus()
    await page.keyboard.press('Enter')
    await expect(toggle).toBeFocused()
  })
})

// Every bundle committed to this repository passes, so the failure-cluster
// explorer renders its empty state against the real dataset and none of its
// interactive markup is ever exercised by the axe sweep above. Substituting the
// response is the only way to put the cards, the expand control and the run
// links in front of axe at all — and markup that only appears when something
// went wrong is exactly the markup nobody checks by hand.
test.describe('failure clusters with failures present', () => {
  const FAILED = [
    {
      bundle: 'synthetic-a', task_id: 'p/one', task_version: '1.0.0', agent: 'scripted',
      success: false, partial_success: false, score_total: 0, steps: 4, tool_calls: 3,
      failed_tool_calls: 1, invalid_tool_calls: 0, repeated_calls: 0, unnecessary_changes: 0,
      workspace_violations: 0, wall_ms: 12, model_ms: null, tool_ms: 4,
      failure_reason: 'policy_violation', trust_state: 'LOCAL', run_id: 'r0',
      created_at: '2026-09-01T00:00:00Z',
      failure_step: { seq: 5, tool: 'shell', reason: 'policy_violation', rule: 'denied_tool', detail: 'shell is not allowed' },
    },
    {
      bundle: 'synthetic-b', task_id: 'p/two', task_version: '1.0.0', agent: 'scripted',
      success: false, partial_success: false, score_total: 0, steps: 4, tool_calls: 3,
      failed_tool_calls: 1, invalid_tool_calls: 0, repeated_calls: 0, unnecessary_changes: 0,
      workspace_violations: 0, wall_ms: 12, model_ms: null, tool_ms: 4,
      failure_reason: 'execution', trust_state: 'LOCAL', run_id: 'r1',
      created_at: '2026-09-01T00:00:00Z',
      failure_step: { seq: 3, tool: 'patch_file', reason: 'execution', rule: 'tool_error', detail: 'patch did not apply' },
    },
  ]

  test.beforeEach(async ({ page }) => {
    await page.route('**/data/results.json', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(FAILED) }),
    )
  })

  test('clusters are expandable and each run links to its failing step', async ({ page }) => {
    await page.goto('/failures')
    const cards = page.locator('.cluster-card')
    await expect(cards).toHaveCount(2)
    // Ranked by size, then by tasks spanned; both are singletons, so assert the
    // behaviour that matters instead: expanding reveals the step link.
    await cards.first().click()
    await expect(cards.first()).toHaveAttribute('aria-expanded', 'true')
    const link = page.getByRole('region', { name: /cluster detail/i }).getByRole('link').first()
    await expect(link).toHaveAttribute('href', /\/results\/synthetic-[ab]\?seq=\d+/)
  })

  test('a nested route opened directly boots at all', async ({ page }) => {
    // The regression this guards: with a relative asset base the page requested
    // its JavaScript from `/results/assets/...`, got a 404, and rendered an
    // empty <div id="root">. Every deep link in the app was dead, in production
    // only, with nothing in the build to say so.
    const failed: string[] = []
    page.on('response', (r) => {
      if (r.status() === 404 && /\.(js|css)$/.test(r.url())) failed.push(r.url())
    })
    await page.goto('/results/synthetic-a?seq=5')
    await expect(page.locator('#root')).not.toBeEmpty()
    expect(failed, 'assets 404d from a nested route').toEqual([])
  })

  test('following a cluster link opens the trace on the attributed step', async ({ page }) => {
    await page.goto('/results/synthetic-a?seq=5')
    // The bundle is not on disk, so there is no trace to show; the attribution
    // itself is what must survive the navigation.
    await expect(page.getByText(/failure attributed to step #5/i)).toBeVisible()
    await expect(page.getByText('denied_tool')).toBeVisible()
  })

  test('a 404.html fallback ships, or every deep link dies on Pages', async ({ request }) => {
    // vite preview has its own SPA fallback, so this asserts the artifact
    // exists rather than the behaviour -- on GitHub Pages the file *is* the
    // behaviour.
    expect((await request.get('/404.html')).status()).toBe(200)
  })

  test('no critical accessibility violations with clusters rendered', async ({ page }) => {
    await page.goto('/failures')
    await page.locator('.cluster-card').first().click()
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(
      serious.flatMap((v) => v.nodes.map((n) => `${v.id}: ${JSON.stringify(n.target)}`)),
      'serious/critical axe violations on the failure-cluster explorer',
    ).toEqual([])
  })
})
