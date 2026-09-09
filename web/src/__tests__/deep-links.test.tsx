import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { assetUrl, getResults } from '../api'
import type { ResultRow } from '../api'
import { CostEfficiencyPage, TraceExplorerPage } from '../pages/operations'

/**
 * Three defects found while building the drill-down from a failure cluster to
 * the exact failing step. Each one is the same shape as the rest of this
 * repository's history: the code was written, and it had never run.
 *
 * 1. Every dataset file was fetched as a bare relative string —
 *    `data/results.json`, `bundles/<name>/trace.json`. A browser resolves those
 *    against the current *route*, so from `/results/<bundle>` they ask for
 *    `/results/data/results.json`. Every load on every nested route was a 404,
 *    and the page then rendered its empty state as though the dataset itself
 *    were empty. Nothing distinguishes "no data" from "wrong URL" in a UI.
 *
 * 2. The Trace Explorer fetched `trace.jsonl` and `workspace.diff` — the names
 *    of the files *inside* a .tooltrace bundle. The generator publishes
 *    `trace.json` and `workspace.diff.txt`. The page had therefore never
 *    displayed a single trace, and said `HTTP 404` where a trace should be.
 *
 * 3. The build used a relative asset base, so a nested route requested its
 *    JavaScript from under that route and the application never booted at all.
 *    That one is not testable here — it is asserted by the end-to-end suite
 *    against the real production build, which is the only place it is real.
 */

describe('assetUrl', () => {
  it('resolves against the site root, not the current route', () => {
    // The exact failure: from /results/<bundle>, a bare relative string means
    // /results/data/results.json.
    expect(assetUrl('data/results.json')).toBe(`${import.meta.env.BASE_URL}data/results.json`)
    expect(assetUrl('data/results.json').startsWith('/')).toBe(true)
  })

  it('does not double the separator when given a rooted path', () => {
    expect(assetUrl('/data/results.json')).toBe(assetUrl('data/results.json'))
  })
})

describe('dataset loaders', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('request an absolute URL so a nested route still finds the data', async () => {
    const fetchMock = vi.fn((_url: string) => Promise.resolve(new Response('[]', { status: 200 })))
    vi.stubGlobal('fetch', fetchMock)
    await getResults()
    const requested = String(fetchMock.mock.calls[0][0])
    expect(requested).toBe(`${import.meta.env.BASE_URL}data/results.json`)
    // The old behaviour, stated as the thing that must not come back.
    expect(requested).not.toBe('data/results.json')
  })
})

describe('TraceExplorerPage', () => {
  const RESULT = {
    bundle: 'b1',
    task_id: 'p/one',
    task_version: '1.0.0',
    agent: 'scripted',
    success: true,
    partial_success: false,
    score_total: 1,
    steps: 2,
    tool_calls: 1,
    failed_tool_calls: 0,
    invalid_tool_calls: 0,
    repeated_calls: 0,
    unnecessary_changes: 0,
    workspace_violations: 0,
    wall_ms: 5,
    model_ms: null,
    tool_ms: 2,
    failure_reason: 'none',
    trust_state: 'LOCAL',
    run_id: 'r0',
    created_at: '2026-09-01T00:00:00Z',
  }

  beforeEach(() => {
    vi.unstubAllGlobals()
    // Serves only the names the generator actually publishes. A request for
    // `trace.jsonl` — what this page asked for before — 404s, which is exactly
    // what happened against the real site.
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        const json = (body: unknown) =>
          Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
        if (url.endsWith('data/results.json')) return json([RESULT])
        if (url.endsWith('data/index.json'))
          return json({ generated_at: '', framework_version: '0', compatibility_key: '', counts: {} })
        if (url.endsWith('bundles/b1/trace.json'))
          return json([
            { seq: 1, ts: 0, type: 'tool_call', payload: { tool: 'read_file' } },
            { seq: 2, ts: 1, type: 'tool_result', payload: { status: 'ok' } },
          ])
        if (url.endsWith('bundles/b1/workspace.diff.txt'))
          return Promise.resolve(new Response('--- a\n+++ b\n', { status: 200 }))
        return Promise.resolve(new Response('not found', { status: 404 }))
      }),
    )
  })

  it('loads a trace from the file the generator actually publishes', async () => {
    render(
      <MemoryRouter>
        <TraceExplorerPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: /trace explorer/i })
    await userEvent.selectOptions(screen.getByRole('combobox'), 'b1')
    // The assertion that fails on the old code: it showed "HTTP 404" here.
    await waitFor(() => expect(screen.queryByText(/HTTP 404/)).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/tool_call/)).toBeInTheDocument())
  })
})

// --- the latency split ------------------------------------------------------

describe('CostEfficiencyPage latency split', () => {
  /**
   * `model_ms` and `tool_ms` were on every row and never shown together, so the
   * page could say a run took 40 ms without saying whether the agent was slow at
   * deciding or slow at acting.
   *
   * The failure mode to guard is the tempting one: when an adapter cannot report
   * inference time, computing harness overhead as `wall - tool` produces a
   * confident number from an unmeasured input, in the one place a reader would
   * trust it.
   */
  function mockRows(rows: Partial<ResultRow>[]) {
    const full = rows.map((r, i) => ({
      bundle: `b${i}`, task_id: 'p/one', task_version: '1.0.0', agent: 'a',
      success: true, partial_success: false, score_total: 1, steps: 2,
      tool_calls: 1, failed_tool_calls: 0, invalid_tool_calls: 0, repeated_calls: 0,
      unnecessary_changes: 0, workspace_violations: 0, wall_ms: 100, model_ms: null,
      tool_ms: 20, failure_reason: 'none', trust_state: 'LOCAL', run_id: `r${i}`,
      created_at: '2026-09-01T00:00:00Z', ...r,
    }))
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) =>
        Promise.resolve(
          new Response(JSON.stringify(url.includes('results.json') ? full : []), { status: 200 }),
        ),
      ),
    )
  }

  beforeEach(() => vi.unstubAllGlobals())

  it('splits the time when every run reports inference', async () => {
    mockRows([{ wall_ms: 100, model_ms: 70, tool_ms: 20 }])
    render(
      <MemoryRouter>
        <CostEfficiencyPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: /where the time goes/i })
    expect(screen.getByText(/70\.0 ms \(70\.0%\)/)).toBeInTheDocument()
    expect(screen.getByText('10.0 ms')).toBeInTheDocument()
  })

  it('leaves harness overhead unknown when inference time is unreported', async () => {
    mockRows([{ wall_ms: 100, model_ms: null, tool_ms: 20 }])
    render(
      <MemoryRouter>
        <CostEfficiencyPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: /where the time goes/i })
    expect(screen.getByText(/unknown while inference time is unreported/i)).toBeInTheDocument()
    // The specific number that must not appear: 100 - 20.
    expect(screen.queryByText('80.0 ms')).not.toBeInTheDocument()
  })

  it('says how much of the sample could answer', async () => {
    mockRows([
      { wall_ms: 100, model_ms: 70, tool_ms: 20 },
      { wall_ms: 100, model_ms: null, tool_ms: 20 },
    ])
    render(
      <MemoryRouter>
        <CostEfficiencyPage />
      </MemoryRouter>,
    )
    await screen.findByRole('heading', { name: /where the time goes/i })
    expect(screen.getByText(/1 of 2 runs report inference time/i)).toBeInTheDocument()
  })
})
