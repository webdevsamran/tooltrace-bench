import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ResultRow } from '../api'
import { UNATTRIBUTED_RULE, clusterFailures, stepLink } from '../lib/clusters'
import { TraceTimeline, type TraceLine } from '../components'
import { FailureAnalysisPage, ResultDetailPage } from '../pages/results'

/**
 * The failure view this replaces was a dropdown and a bar chart of the twelve
 * failure *categories*. It could tell a reader that eleven runs hit
 * `execution`, and could not tell them whether that was one bug or eleven — nor
 * where in any trace to look afterwards.
 *
 * Clustering only helps if it separates things that are actually different, so
 * that is what most of this file asserts: two runs sharing a category but not a
 * rule must not merge, and two runs sharing a rule but not a tool must not
 * merge either. A clusterer that lumps everything together would show one
 * enormous "execution" cluster and be strictly worse than the bar chart.
 *
 * The other half is the drill-down. A cluster that cannot be opened at the
 * exact step is a prettier bar chart, so the link, the highlight and the
 * unattributed case are all tested.
 */

function row(over: Partial<ResultRow> & { bundle: string }): ResultRow {
  return {
    task_id: 'file-editing/fix-config-typo',
    task_version: '1.0.0',
    agent: 'scripted',
    success: false,
    partial_success: false,
    score_total: 0,
    steps: 4,
    tool_calls: 3,
    failed_tool_calls: 1,
    invalid_tool_calls: 0,
    repeated_calls: 0,
    unnecessary_changes: 0,
    workspace_violations: 0,
    wall_ms: 12,
    model_ms: null,
    tool_ms: 4,
    failure_reason: 'execution',
    trust_state: 'LOCAL',
    run_id: 'run-0',
    created_at: '2026-09-01T00:00:00Z',
    failure_step: null,
    ...over,
  }
}

const step = (seq: number, tool: string, rule: string, reason = 'execution') => ({
  seq,
  tool,
  reason,
  rule,
  detail: `${tool} failed`,
})

// --- the clustering itself --------------------------------------------------

describe('clusterFailures', () => {
  it('ignores runs that passed', () => {
    const clusters = clusterFailures([
      row({ bundle: 'a', success: true, failure_reason: 'none' }),
      row({ bundle: 'b', failure_step: step(3, 'patch_file', 'tool_error') }),
    ])
    expect(clusters).toHaveLength(1)
    expect(clusters[0].runs.map((r) => r.bundle)).toEqual(['b'])
  })

  it('merges runs that share a full signature', () => {
    const clusters = clusterFailures([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', run_id: 'run-1', failure_step: step(3, 'patch_file', 'tool_error') }),
    ])
    expect(clusters).toHaveLength(1)
    expect(clusters[0].runs).toHaveLength(2)
  })

  it('does NOT merge the same category reached by different rules', () => {
    // The precise failing of the old category view: both of these were one bar.
    const clusters = clusterFailures([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', failure_step: step(3, 'patch_file', 'repeated_failing_call') }),
    ])
    expect(clusters).toHaveLength(2)
  })

  it('does NOT merge the same rule attributed to different tools', () => {
    const clusters = clusterFailures([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', failure_step: step(3, 'run_process', 'tool_error') }),
    ])
    expect(clusters).toHaveLength(2)
    expect(clusters.map((c) => c.tool).sort()).toEqual(['patch_file', 'run_process'])
  })

  it('ranks the biggest cluster first', () => {
    const clusters = clusterFailures([
      row({ bundle: 'a', failure_step: step(1, 'shell', 'denied_tool', 'policy_violation') }),
      row({ bundle: 'b', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'c', failure_step: step(3, 'patch_file', 'tool_error') }),
    ])
    expect(clusters[0].rule).toBe('tool_error')
    expect(clusters[0].runs).toHaveLength(2)
  })

  it('breaks a size tie on how many tasks the cluster spans', () => {
    // Equal counts, but one is systemic across tasks and the other is not.
    const clusters = clusterFailures([
      row({ bundle: 'a', task_id: 'x/one', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', task_id: 'x/two', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'c', task_id: 'x/one', failure_step: step(1, 'shell', 'denied_tool') }),
      row({ bundle: 'd', task_id: 'x/one', failure_step: step(1, 'shell', 'denied_tool') }),
    ])
    expect(clusters[0].tasks).toHaveLength(2)
    expect(clusters[0].rule).toBe('tool_error')
  })

  it('gives a cluster a representative seq only when every run agrees', () => {
    const same = clusterFailures([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', failure_step: step(3, 'patch_file', 'tool_error') }),
    ])
    expect(same[0].representativeSeq).toBe(3)

    const differing = clusterFailures([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', failure_step: step(7, 'patch_file', 'tool_error') }),
    ])
    // Showing one run's step as the cluster's would be a guess presented as
    // a fact about all of them.
    expect(differing[0].representativeSeq).toBeNull()
  })

  it('keeps unattributed failures rather than dropping them', () => {
    // An index generated before attribution existed has no failure_step at all.
    // Those runs must still appear, labelled as what they are.
    const clusters = clusterFailures([row({ bundle: 'a', failure_step: undefined })])
    expect(clusters).toHaveLength(1)
    expect(clusters[0].rule).toBe(UNATTRIBUTED_RULE)
    expect(clusters[0].representativeSeq).toBeNull()
  })
})

describe('stepLink', () => {
  it('carries the attributed step in the URL', () => {
    expect(stepLink(row({ bundle: 'b1', failure_step: step(5, 'shell', 'denied_tool') }))).toBe(
      '/results/b1?seq=5',
    )
  })

  it('links to the run without a step when nothing was attributed', () => {
    expect(stepLink(row({ bundle: 'b1' }))).toBe('/results/b1')
  })

  it('escapes a bundle name so a link cannot be broken by one', () => {
    expect(stepLink(row({ bundle: 'a b/c' }))).toBe('/results/a%20b%2Fc')
  })
})

// --- the page ---------------------------------------------------------------

function mockResults(rows: ResultRow[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const body = url.includes('results.json') ? rows : []
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
    }),
  )
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/failures']}>
      <Routes>
        <Route path="/failures" element={<FailureAnalysisPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('failure cluster explorer', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    // `useUrlState` reads and writes the real `window.location`, which jsdom
    // shares across tests in a file. Without this reset, a test that opens a
    // cluster leaves the next one already expanded.
    window.history.replaceState(null, '', '/failures')
  })

  it('says there is nothing to cluster when no run failed', async () => {
    // The state of this repository's own dataset: every committed bundle
    // passes. The page must say so, not render an empty chart.
    mockResults([row({ bundle: 'a', success: true, failure_reason: 'none' })])
    renderPage()
    expect(await screen.findByText(/nothing to cluster/i)).toBeInTheDocument()
  })

  it('reports how many failures are openable at a step', async () => {
    mockResults([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', failure_step: undefined }),
    ])
    renderPage()
    expect(await screen.findByText('1 / 2')).toBeInTheDocument()
  })

  it('opens a cluster and links each run to its failing step', async () => {
    mockResults([
      row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') }),
      row({ bundle: 'b', run_id: 'r1', failure_step: step(3, 'patch_file', 'tool_error') }),
    ])
    renderPage()
    const card = await screen.findByRole('button', { expanded: false })
    await userEvent.click(card)

    const detail = screen.getByRole('region', { name: /cluster detail/i })
    const links = within(detail).getAllByRole('link')
    expect(links).toHaveLength(2)
    expect(links[0]).toHaveAttribute('href', '/results/a?seq=3')
    expect(within(detail).getAllByText(/open at step #3/i)).toHaveLength(2)
  })

  it('puts the open cluster in the URL so the view can be linked', async () => {
    mockResults([row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') })])
    renderPage()
    await userEvent.click(await screen.findByRole('button', { expanded: false }))
    await waitFor(() =>
      expect(new URLSearchParams(window.location.search).get('cluster')).toContain('tool_error'),
    )
  })

  it('says so plainly when a run in a cluster has no step to open', async () => {
    mockResults([row({ bundle: 'a', failure_step: undefined })])
    renderPage()
    await userEvent.click(await screen.findByRole('button', { expanded: false }))
    expect(screen.getByText(/no step attributed/i)).toBeInTheDocument()
  })

  it('announces the detail pane so a screen reader hears the selection', async () => {
    mockResults([row({ bundle: 'a', failure_step: step(3, 'patch_file', 'tool_error') })])
    renderPage()
    await screen.findByRole('button', { expanded: false })
    const detail = screen.getByRole('region', { name: /cluster detail/i })
    expect(detail).toHaveAttribute('aria-live', 'polite')
  })
})

// --- landing on the step ----------------------------------------------------

describe('TraceTimeline highlightSeq', () => {
  const trace: TraceLine[] = [
    { seq: 1, type: 'tool_request', tool: 'read_file' },
    { seq: 5, type: 'tool_result', tool: 'shell', status: 'denied' },
    { seq: 9, type: 'tool_result', tool: 'read_file', status: 'ok' },
  ]

  it('marks the attributed row and only that row', () => {
    render(<TraceTimeline events={trace} highlightSeq={5} />)
    const marked = screen.getAllByRole('option').filter((o) => o.dataset.attributed === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0]).toHaveTextContent('#5')
  })

  it('carries the marking to a screen reader, not only to the eye', () => {
    // The row is tinted red. Tint alone reaches nobody using a screen reader
    // and nobody with the colour removed, so the state is in the name too.
    render(<TraceTimeline events={trace} highlightSeq={5} />)
    expect(screen.getByRole('option', { name: /failure attributed here/i })).toBeInTheDocument()
  })

  it('starts keyboard focus on the attributed row rather than the first', () => {
    render(<TraceTimeline events={trace} highlightSeq={9} />)
    const options = screen.getAllByRole('option')
    expect(options[2]).toHaveAttribute('aria-selected', 'true')
    expect(options[0]).toHaveAttribute('aria-selected', 'false')
  })

  it('marks nothing when the seq is not in the trace', () => {
    // A stale link must not highlight an unrelated row by index.
    render(<TraceTimeline events={trace} highlightSeq={999} />)
    expect(screen.queryAllByRole('option').filter((o) => o.dataset.attributed === 'true')).toHaveLength(0)
  })

  it('marks nothing when no step was given', () => {
    render(<TraceTimeline events={trace} />)
    expect(screen.queryAllByRole('option').filter((o) => o.dataset.attributed === 'true')).toHaveLength(0)
  })
})

describe('ResultDetailPage arriving from a cluster', () => {
  const failing = row({
    bundle: 'b1',
    run_id: 'run-9',
    failure_reason: 'policy_violation',
    failure_step: { seq: 5, tool: 'shell', reason: 'policy_violation', rule: 'denied_tool', detail: 'shell is not allowed' },
  })

  function mockDetail(rows: ResultRow[]) {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('results.json'))
          return Promise.resolve(new Response(JSON.stringify(rows), { status: 200 }))
        if (url.includes('trace.json'))
          return Promise.resolve(
            new Response(
              JSON.stringify([
                { seq: 1, type: 'tool_request', tool: 'read_file' },
                { seq: 5, type: 'tool_result', tool: 'shell', status: 'denied' },
              ]),
              { status: 200 },
            ),
          )
        return Promise.resolve(new Response('', { status: 200 }))
      }),
    )
  }

  function renderDetail(search: string) {
    window.history.replaceState(null, '', `/results/b1${search}`)
    return render(
      <MemoryRouter initialEntries={[`/results/b1${search}`]}>
        <Routes>
          <Route path="/results/:bundle" element={<ResultDetailPage />} />
        </Routes>
      </MemoryRouter>,
    )
  }

  beforeEach(() => {
    vi.unstubAllGlobals()
    window.history.replaceState(null, '', '/')
  })

  it('opens on the step named in the link', async () => {
    mockDetail([failing])
    renderDetail('?seq=5')
    await screen.findByRole('heading', { name: /result/i })
    const marked = screen.getAllByRole('option').filter((o) => o.dataset.attributed === 'true')
    expect(marked).toHaveLength(1)
    expect(marked[0]).toHaveTextContent('#5')
  })

  it('falls back to the attributed step when the link carries none', async () => {
    // Reaching the page any other way should still land on the failure.
    mockDetail([failing])
    renderDetail('')
    await screen.findByRole('heading', { name: /result/i })
    expect(screen.getAllByRole('option').filter((o) => o.dataset.attributed === 'true')).toHaveLength(1)
  })

  it('states the rule and the tool, not just the category', async () => {
    mockDetail([failing])
    renderDetail('?seq=5')
    await screen.findByRole('heading', { name: /result/i })
    expect(screen.getByText(/failure attributed to step #5/i)).toBeInTheDocument()
    expect(screen.getByText('denied_tool')).toBeInTheDocument()
    expect(screen.getByText(/shell is not allowed/)).toBeInTheDocument()
  })

  it('shows no attribution callout for a run that passed', async () => {
    mockDetail([row({ bundle: 'b1', success: true, failure_reason: 'none' })])
    renderDetail('')
    await screen.findByRole('heading', { name: /result/i })
    expect(screen.queryByText(/failure attributed to step/i)).not.toBeInTheDocument()
  })

  it('ignores a non-numeric seq rather than throwing', async () => {
    mockDetail([failing])
    renderDetail('?seq=not-a-number')
    await screen.findByRole('heading', { name: /result/i })
    // Falls back to the attributed step; the page renders either way.
    expect(screen.getAllByRole('option').length).toBeGreaterThan(0)
  })
})
