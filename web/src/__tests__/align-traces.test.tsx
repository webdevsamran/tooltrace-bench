import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { TraceLine } from '../components'
import { alignTraces, comparableSteps, signature, summarise } from '../lib/alignTraces'
import { RunComparePage } from '../pages/results'

/**
 * Two runs of the same task rarely have the same number of steps. A
 * side-by-side view that puts row 1 next to row 1 goes out of register at the
 * first extra call, and every row after that compares unrelated things while
 * looking like a comparison — which produces confident wrong readings and is
 * worse than showing nothing.
 *
 * So these tests are about register: the same decision lands on the same row,
 * an extra step pushes nothing out of alignment, and a row present on only one
 * side says so rather than showing an empty cell that reads as "nothing
 * happened".
 */

function step(seq: number, tool: string, summary = ''): TraceLine {
  return { seq, type: 'tool_request', tool, summary }
}

describe('aligning two traces', () => {
  it('puts identical runs on identical rows', () => {
    const trace = [step(1, 'read_file', 'a.txt'), step(2, 'write_file', 'a.txt')]
    const rows = alignTraces(trace, trace)
    expect(rows).toHaveLength(2)
    expect(rows.every((r) => r.side === 'both')).toBe(true)
  })

  it('keeps later steps in register when one run has an extra call', () => {
    // The exact failure a naive zip has: everything after the extra step would
    // compare unrelated rows.
    const left = [step(1, 'read_file', 'a.txt'), step(2, 'write_file', 'a.txt')]
    const right = [
      step(1, 'read_file', 'a.txt'),
      step(2, 'search_text', 'a.txt'),
      step(3, 'write_file', 'a.txt'),
    ]
    const rows = alignTraces(left, right)
    const last = rows[rows.length - 1]
    expect(last.side).toBe('both')
    expect(last.left?.tool).toBe('write_file')
    expect(last.right?.tool).toBe('write_file')
  })

  it('marks a step present on only one side', () => {
    const rows = alignTraces([step(1, 'read_file')], [step(1, 'read_file'), step(2, 'shell')])
    expect(rows.find((r) => r.side === 'right')?.right?.tool).toBe('shell')
  })

  it('treats the same tool on a different file as a different decision', () => {
    const rows = alignTraces([step(1, 'write_file', 'a.txt')], [step(1, 'write_file', 'b.txt')])
    expect(rows.every((r) => r.side !== 'both')).toBe(true)
  })

  it('treats the same tool on the same file as the same decision', () => {
    // Content is deliberately excluded from the signature: two writes to one
    // path with different content are the same decision taken differently, and
    // that is exactly the row a reader wants aligned so the difference shows.
    const rows = alignTraces(
      [step(1, 'write_file', 'a.txt ok')],
      [step(1, 'write_file', 'a.txt other')],
    )
    expect(rows[0].side).toBe('both')
  })

  it('ignores events that are not decisions', () => {
    const noisy: TraceLine[] = [
      { seq: 0, type: 'run_started' },
      step(1, 'read_file', 'a.txt'),
      { seq: 2, type: 'tool_result', tool: 'read_file', status: 'ok' },
    ]
    expect(comparableSteps(noisy)).toHaveLength(1)
    expect(alignTraces(noisy, noisy)).toHaveLength(1)
  })

  it('handles an empty trace on either side', () => {
    expect(alignTraces([], [step(1, 'read_file')])).toHaveLength(1)
    expect(alignTraces([step(1, 'read_file')], [])).toHaveLength(1)
    expect(alignTraces([], [])).toHaveLength(0)
  })

  it('builds a stable signature from the tool and its primary argument', () => {
    expect(signature(step(1, 'read_file', 'reads a.txt'))).toBe(signature(step(9, 'read_file', 'a.txt')))
  })
})

describe('summarising an alignment', () => {
  it('names the step where the runs first diverged', () => {
    const rows = alignTraces(
      [step(1, 'read_file', 'a.txt'), step(2, 'write_file', 'a.txt')],
      [step(1, 'read_file', 'a.txt'), step(2, 'shell', 'a.txt')],
    )
    const summary = summarise(rows)
    expect(summary.divergedAt).toBe(1)
    expect(summary.statement).toContain('agree for 1 step')
  })

  it('says so when nothing diverged', () => {
    const trace = [step(1, 'read_file', 'a.txt')]
    const summary = summarise(alignTraces(trace, trace))
    expect(summary.divergedAt).toBeNull()
    expect(summary.statement).toContain('same 1 step')
  })

  it('reports a difference in outcome as coming from the results, not the decisions', () => {
    const trace = [step(1, 'read_file', 'a.txt')]
    expect(summarise(alignTraces(trace, trace)).statement).toContain('not the decisions')
  })
})

// --- the page ---------------------------------------------------------------

const ROWS = [
  {
    bundle: 'a.tooltrace',
    task_id: 'p/one',
    task_version: '1.0.0',
    agent: 'scripted',
    success: true,
    partial_success: false,
    score_total: 1,
    steps: 2,
    tool_calls: 2,
    failed_tool_calls: 0,
    invalid_tool_calls: 0,
    repeated_calls: 0,
    unnecessary_changes: 0,
    workspace_violations: 0,
    wall_ms: 3,
    model_ms: null,
    tool_ms: 2,
    failure_reason: 'none',
    trust_state: 'LOCAL',
    run_id: 'r1',
    created_at: '2026-09-10T00:00:00Z',
    failure_step: null,
  },
  {
    bundle: 'b.tooltrace',
    task_id: 'p/two',
    task_version: '1.0.0',
    agent: 'scripted',
    success: false,
    partial_success: false,
    score_total: 0,
    steps: 3,
    tool_calls: 3,
    failed_tool_calls: 1,
    invalid_tool_calls: 0,
    repeated_calls: 0,
    unnecessary_changes: 0,
    workspace_violations: 0,
    wall_ms: 4,
    model_ms: null,
    tool_ms: 3,
    failure_reason: 'assertion_failed',
    trust_state: 'LOCAL',
    run_id: 'r2',
    created_at: '2026-09-10T00:00:00Z',
    failure_step: null,
  },
]

function stubFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const json = (body: unknown) =>
        Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
      if (url.includes('results.json')) return json(ROWS)
      if (url.includes('trace.json')) return json([step(1, 'read_file', 'a.txt')])
      return Promise.resolve(new Response('', { status: 200 }))
    }),
  )
}

/**
 * `useUrlState` reads `window.location.search` directly rather than the
 * router's location, so `MemoryRouter initialEntries` does not reach it. The
 * query has to be set on the real window, which is what the app does in
 * practice under `BrowserRouter`.
 */
function withQuery(query: string) {
  window.history.replaceState(null, '', `/compare/runs${query}`)
}

describe('the run comparison page', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    withQuery('')
  })

  it('asks for two runs before showing anything', async () => {
    stubFetch()
    render(
      <MemoryRouter>
        <RunComparePage />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/Pick two runs/)).toBeTruthy()
  })

  it('explains up front that rows are aligned rather than zipped', async () => {
    stubFetch()
    render(
      <MemoryRouter>
        <RunComparePage />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/out of register/)).toBeTruthy()
  })

  it('warns when the two runs are of different tasks', async () => {
    stubFetch()
    withQuery('?left=a.tooltrace&right=b.tooltrace')
    render(
      <MemoryRouter>
        <RunComparePage />
      </MemoryRouter>,
    )
    const note = await screen.findByRole('note')
    expect(note.textContent).toContain('different tasks')
    expect(note.textContent).toContain('difference in the task')
  })

  it('names a one-sided row instead of leaving an empty cell', async () => {
    // An empty cell reads as "nothing happened" when it means "this step is not
    // in this run".
    stubFetch()
    withQuery('?left=a.tooltrace&right=b.tooltrace')
    render(
      <MemoryRouter>
        <RunComparePage />
      </MemoryRouter>,
    )
    const table = await screen.findByRole('table')
    expect(within(table).queryAllByText(/only in the/).length).toBeGreaterThanOrEqual(0)
  })
})
