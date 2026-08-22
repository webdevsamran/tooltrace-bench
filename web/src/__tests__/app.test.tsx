import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'

// Mock the static data endpoints so tests are deterministic and offline.
vi.stubGlobal('fetch', vi.fn((url: string) => {
  const json = (body: unknown) =>
    Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
  if (url.includes('index.json')) {
    return json({
      generated_at: '2026-01-01T00:00:00Z', framework_version: '0.1.0',
      compatibility_key: 'protocol=1;trace=1;result=1',
      counts: { tasks: 2, results: 2, agents: 1, packs: 2 },
    })
  }
  if (url.includes('tasks.json')) {
    return json([
      { id: 'p/t1', version: '1.0.0', category: 'c1', difficulty: 'easy',
        tags: [], max_steps: 5, perturbations: [] },
    ])
  }
  if (url.includes('agents.json')) {
    return json([
      { name: 'scripted', runs: 2, success_rate: 1.0, mean_score: 1.0,
        mean_steps: 3, failed_tool_calls_mean: 0, wall_ms_p95: 4 },
    ])
  }
  if (url.includes('results.json')) {
    return json([
      { bundle: 'b.tooltrace', task_id: 'p/t1', task_version: '1.0.0',
        agent: 'scripted', success: true, partial_success: false,
        score_total: 1, steps: 3, tool_calls: 2, failed_tool_calls: 0,
        invalid_tool_calls: 0, repeated_calls: 0, unnecessary_changes: 0,
        workspace_violations: 0, wall_ms: 3, model_ms: null, tool_ms: 2,
        failure_reason: 'none', trust_state: 'LOCAL', run_id: 'r1',
        created_at: '2026-01-01T00:00:00Z' },
    ])
  }
  return Promise.resolve(new Response('{}', { status: 404 }))
}))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('App routes', () => {
  it('renders the home page with real index counts', async () => {
    renderAt('/')
    expect(await screen.findByRole('heading', { name: /tooltrace bench/i })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('validated results')).toBeInTheDocument())
  })

  it('renders the leaderboard from agent data', async () => {
    renderAt('/leaderboard')
    expect(await screen.findByRole('heading', { name: /leaderboard/i })).toBeInTheDocument()
    expect(await screen.findByText('scripted')).toBeInTheDocument()
    expect(screen.getByText('100.0%')).toBeInTheDocument()
  })

  it('renders task packs table with a link to detail', async () => {
    renderAt('/tasks')
    expect(await screen.findByText('p/t1')).toBeInTheDocument()
  })

  it('shows empty state on failure analysis when nothing failed', async () => {
    renderAt('/failures')
    expect(
      await screen.findByText(/No failures recorded/i),
    ).toBeInTheDocument()
  })

  it('renders methodology content', () => {
    renderAt('/methodology')
    expect(screen.getByRole('heading', { name: /methodology/i })).toBeInTheDocument()
  })
})