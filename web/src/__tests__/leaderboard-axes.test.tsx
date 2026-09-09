import { render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LeaderboardPage } from '../pages/browse'

/**
 * The four-axis leaderboard: accuracy, cost, latency, security resilience.
 *
 * The failure mode this guards against is specific. An axis nobody measured,
 * rendered as a number, reads as a *good* score: a null cost shown as `0` is
 * "free", and a null attack-success-rate shown as `0%` is "perfectly secure".
 * Both would be the most misleading numbers on the page, and both are null for
 * every agent in this repository today — no adapter reports spend, and no
 * security pack ships (`docs/feature-status.md` row 16 is graded `S`).
 *
 * So the rule is: unmeasured renders as "not measured", with a reason.
 */

const AGENT = {
  name: 'scripted',
  runs: 6,
  success_rate: 1.0,
  mean_score: 1.0,
  mean_steps: 3,
  failed_tool_calls_mean: 0,
  wall_ms_p95: 33,
  cost_per_resolved_task: null as number | null,
  total_cost: null as number | null,
  priced_runs: 0,
  currency: null as string | null,
  attack_success_rate: null as number | null,
  security_runs: 0,
}

function mockData(agent: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => {
      const json = (body: unknown) =>
        Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
      if (url.includes('agents.json')) return json([agent])
      if (url.includes('results.json')) return json([])
      if (url.includes('tasks.json')) return json([])
      return Promise.resolve(new Response('[]', { status: 200 }))
    }),
  )
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LeaderboardPage />
    </MemoryRouter>,
  )
}

describe('four-axis leaderboard', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('shows all four axes as columns', async () => {
    mockData(AGENT)
    renderPage()
    expect(await screen.findByRole('heading', { name: /leaderboard/i })).toBeInTheDocument()
    for (const header of [/success rate/i, /cost \/ resolved task/i, /p95 wall ms/i, /attack success/i]) {
      expect(screen.getByRole('button', { name: header })).toBeInTheDocument()
    }
  })

  it('renders an unmeasured cost as "not measured", never as zero', async () => {
    mockData(AGENT)
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    await waitFor(() => expect(screen.getAllByText(/not measured/i).length).toBeGreaterThan(0))
    // The specific danger: a currency-formatted zero.
    expect(screen.queryByText(/0\.0000/)).not.toBeInTheDocument()
  })

  it('renders an unmeasured attack-success rate as "not measured", never as 0%', async () => {
    mockData(AGENT)
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    // Scoped to the table: the explanatory note also uses the phrase.
    const table = await screen.findByRole('table')
    await waitFor(() => expect(within(table).getAllByText(/not measured/i)).toHaveLength(2))
    expect(within(table).queryByText(/0\.0% of/)).not.toBeInTheDocument()
  })

  it('says plainly which axes this dataset does not measure', async () => {
    mockData(AGENT)
    renderPage()
    const note = await screen.findByRole('note')
    expect(note).toHaveTextContent(/cost and security are unmeasured/i)
    expect(note).toHaveTextContent(/would look like free, or perfectly secure/i)
  })

  it('counts how many agents have each axis measured', async () => {
    mockData(AGENT)
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    // Latency is always measured; cost and security are not.
    expect(screen.getByText('1/1')).toBeInTheDocument()
    expect(screen.getAllByText('0/1')).toHaveLength(2)
  })

  it('renders real values when the axes are measured', async () => {
    mockData({
      ...AGENT,
      cost_per_resolved_task: 0.1234,
      currency: 'USD',
      priced_runs: 6,
      attack_success_rate: 0.25,
      security_runs: 8,
    })
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    await waitFor(() => expect(screen.getByText(/0\.1234/)).toBeInTheDocument())
    expect(screen.getByText(/25\.0% of 8/)).toBeInTheDocument()
    expect(screen.queryByText(/not measured/i)).not.toBeInTheDocument()
  })

  it('treats a missing field the same as an explicit null', async () => {
    /** Data generated before these fields existed omits them entirely. */
    const { cost_per_resolved_task, attack_success_rate, ...older } = AGENT
    void cost_per_resolved_task
    void attack_success_rate
    mockData(older)
    renderPage()
    const table = await screen.findByRole('table')
    await waitFor(() => expect(within(table).getAllByText(/not measured/i)).toHaveLength(2))
  })

  it('flags a measured attack-success rate above zero as bad', async () => {
    mockData({ ...AGENT, attack_success_rate: 0.5, security_runs: 4 })
    const { container } = renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    await waitFor(() => expect(container.querySelector('.badge-bad')).toBeTruthy())
  })

  it('does NOT mark a fully resisted small sample as good', async () => {
    // Four resisted attempts have a Wilson upper bound near 50%. A green badge
    // there is a stronger claim than "not measured" was, because it looks like
    // a finding rather than an absence.
    mockData({
      ...AGENT,
      attack_success_rate: 0,
      security_runs: 4,
      attack_ci95: [0, 0.4899],
      security_sample_is_small: true,
    })
    const { container } = renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    await waitFor(() => expect(container.querySelector('.badge-warn')).toBeTruthy())
    expect(container.querySelector('.badge-ok')).toBeNull()
  })

  it('shows the interval next to the rate, not only on hover', async () => {
    // A tooltip is unavailable to a touch reader, and the upper bound is the
    // whole point of showing a rate over a handful of attempts.
    mockData({
      ...AGENT,
      attack_success_rate: 0,
      security_runs: 4,
      attack_ci95: [0, 0.4899],
      security_sample_is_small: true,
    })
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    await waitFor(() => expect(screen.getByText(/≤49%/)).toBeInTheDocument())
  })

  it('marks a fully resisted large sample as good', async () => {
    mockData({
      ...AGENT,
      attack_success_rate: 0,
      security_runs: 200,
      attack_ci95: [0, 0.0188],
      security_sample_is_small: false,
    })
    const { container } = renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    await waitFor(() => expect(container.querySelector('.badge-ok')).toBeTruthy())
  })
})

/**
 * The badge embed. A README is the one place a reliability number reaches people
 * who will never open the run behind it, so the snippet has to work and the
 * caveat has to travel with it.
 */
describe('badge embed', () => {
  beforeEach(() => vi.unstubAllGlobals())

  it('shows the badge generated from this dataset', async () => {
    mockData(AGENT)
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    const img = await screen.findByRole('img', { name: /reliability badge/i })
    expect(img).toHaveAttribute('src', expect.stringContaining('badge/reliability.svg'))
  })

  it('offers a snippet that points at the badge, not at a placeholder', async () => {
    mockData(AGENT)
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    const snippet = await screen.findByText(/!\[Agent reliability\]/)
    expect(snippet.textContent).toContain('badge/reliability.svg')
    expect(snippet.textContent).toContain('leaderboard')
  })

  it('states the colour rule, because copying the snippet publishes the number', async () => {
    mockData(AGENT)
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    expect(await screen.findByText(/lower bound, not the success rate/i)).toBeInTheDocument()
  })

  it('falls back to "select and copy" when the clipboard is unavailable', async () => {
    // Insecure origins, some webviews, and a denied permission. A button that
    // silently fails is worse than one that says it cannot.
    mockData(AGENT)
    vi.stubGlobal('navigator', {
      clipboard: { writeText: () => Promise.reject(new Error('denied')) },
    })
    renderPage()
    await screen.findByRole('heading', { name: /leaderboard/i })
    const button = await screen.findByRole('button', { name: 'Copy' })
    button.click()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /select and copy/i })).toBeInTheDocument(),
    )
  })
})
