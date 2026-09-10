import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ParetoData } from '../api'
import { ParetoChart } from '../charts'
import { ParetoExplorerPage } from '../pages/operations'

/**
 * `pareto_frontier` shipped with no caller outside its own tests, so the
 * question it answers — which agents is nobody beating on both accuracy and
 * cost at once — could be computed and was never asked. This page is the asking,
 * and most of what is tested here is what it refuses to draw.
 *
 * The dangerous case is an agent with no measured cost. Plotted at zero it would
 * sit at the cheap end of the chart and land on the frontier by default, and the
 * chart would then be recommending the one agent nobody has priced. So an
 * unpriced agent is named in prose above the chart and left off it.
 */

const DATA: ParetoData = {
  generated_at: '2026-09-10T00:00:00Z',
  points: [
    {
      agent: 'careful',
      success_rate: 0.9,
      cost_per_resolved_task: 0.4,
      total_cost: 3.6,
      priced_runs: 10,
      runs: 10,
    },
    {
      agent: 'cheap',
      success_rate: 0.6,
      cost_per_resolved_task: 0.1,
      total_cost: 0.6,
      priced_runs: 10,
      runs: 10,
    },
    {
      agent: 'wasteful',
      success_rate: 0.5,
      cost_per_resolved_task: 0.9,
      total_cost: 4.5,
      priced_runs: 10,
      runs: 10,
    },
    {
      agent: 'unmeasured',
      success_rate: 1.0,
      cost_per_resolved_task: null,
      total_cost: null,
      priced_runs: 0,
      runs: 4,
    },
  ],
  frontier: ['careful', 'cheap'],
  unpriced: ['unmeasured'],
  statement: '2 of 3 agents are on the frontier; the rest are beaten on both accuracy and cost at once',
}

function stub(data: ParetoData | null, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() =>
      Promise.resolve(new Response(JSON.stringify(data ?? {}), { status })),
    ),
  )
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ParetoExplorerPage />
    </MemoryRouter>,
  )
}

describe('the cost–accuracy frontier', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('names the agents it could not plot, rather than dropping them', async () => {
    stub(DATA)
    renderPage()
    const notice = await screen.findByRole('note')
    expect(notice.textContent).toContain('1 agent(s) have no measured cost')
    expect(notice.textContent).toContain('unmeasured')
  })

  it('says why an unpriced agent is not treated as free', async () => {
    stub(DATA)
    renderPage()
    expect(
      await screen.findByText(/would place it on the frontier by default/),
    ).toBeTruthy()
  })

  it('marks a dominated agent as dominated in the table', async () => {
    stub(DATA)
    renderPage()
    const table = await screen.findByRole('table')
    const wasteful = within(table)
      .getAllByRole('row')
      .find((row) => row.textContent?.includes('wasteful'))
    expect(wasteful?.textContent).toContain('dominated')
  })

  it('never shows an unpriced agent as costing zero', async () => {
    stub(DATA)
    renderPage()
    await screen.findByText(/no measured cost/)
    expect(screen.queryByText('0')).toBeNull()
  })

  it('refuses to draw a frontier from a single priced agent', async () => {
    stub({
      ...DATA,
      points: [DATA.points[0], DATA.points[3]],
      frontier: ['careful'],
      statement: 'a frontier drawn from one agent names that agent and means nothing',
    })
    renderPage()
    expect(await screen.findByText(/means nothing/)).toBeTruthy()
  })

  it('says nothing was priced when nothing was priced', async () => {
    stub({ ...DATA, points: [DATA.points[3]], frontier: [], unpriced: ['unmeasured'] })
    renderPage()
    expect(await screen.findByText(/No run in this dataset reported spend/)).toBeTruthy()
  })
})

describe('the chart itself', () => {
  it('labels every point for a reader who cannot see it', () => {
    render(
      <ParetoChart points={DATA.points} frontier={DATA.frontier} />,
    )
    expect(
      screen.getByRole('button', { name: /careful.*on the frontier/i }),
    ).toBeTruthy()
    expect(screen.getByRole('button', { name: /wasteful.*dominated/i })).toBeTruthy()
  })

  it('leaves an unpriced agent off the plot entirely', () => {
    render(<ParetoChart points={DATA.points} frontier={DATA.frontier} />)
    expect(screen.queryByRole('button', { name: /unmeasured/i })).toBeNull()
  })

  it('distinguishes frontier from dominated by shape, not only colour', () => {
    const { container } = render(
      <ParetoChart points={DATA.points} frontier={DATA.frontier} />,
    )
    // Two frontier agents render as rotated squares, one dominated as a circle.
    expect(container.querySelectorAll('rect').length).toBe(2)
    expect(container.querySelectorAll('circle').length).toBe(1)
  })

  it('renders nothing rather than an empty axis when no agent is priced', () => {
    const { container } = render(
      <ParetoChart points={[DATA.points[3]]} frontier={[]} />,
    )
    expect(container.querySelector('svg')).toBeNull()
  })

  it('keeps the accuracy axis at 0–100% instead of auto-scaling', () => {
    render(<ParetoChart points={DATA.points} frontier={DATA.frontier} />)
    // Auto-scaling would make a 40-point spread fill the plot and read as a
    // far bigger difference than it is.
    expect(screen.getByText('0%')).toBeTruthy()
    expect(screen.getByText('100%')).toBeTruthy()
  })
})
