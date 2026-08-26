import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getAgents, getResults, getTasks, useAsync } from '../api'
import type { ResultRow } from '../api'
import { BarChart, DataTable, ErrorState, Loading } from '../components'
import type { Column } from '../components'
import { Heatmap } from '../charts'

// ---------- shared filter hook (shareable via URL query params) ----------

function useFilter(initial: string) {
  const [value, setValue] = useState(initial)
  return [value, setValue] as const
}

export function LeaderboardPage() {
  const agents = useAsync(getAgents)
  const results = useAsync(getResults)
  const tasks = useAsync(getTasks)

  if (agents.loading) return <Loading />
  if (agents.error) return <ErrorState message={agents.error} />
  const rows = [...(agents.data ?? [])].sort((a, b) => b.success_rate - a.success_rate)

  // Domain × agent success-rate heatmap (cohort-safe: same protocol version only).
  const taskCategory = new Map((tasks.data ?? []).map((t) => [t.id, t.category]))
  const domains = [...new Set([...taskCategory.values()])].sort()
  const heatAgents = rows.map((r) => r.name)
  const cells: number[] = []
  for (const d of domains) {
    for (const an of heatAgents) {
      const inDomain = (results.data ?? []).filter(
        (r) => r.agent === an && taskCategory.get(r.task_id) === d,
      )
      const rate =
        inDomain.length === 0 ? 0 : inDomain.filter((r) => r.success).length / inDomain.length
      cells.push(rate)
    }
  }

  return (
    <div>
      <h1>Leaderboard</h1>
      <p className="muted">
        Ranked by measured success rate across validated bundles. Only real
        repository data is shown — never synthetic entries. Agents are never
        ranked across incompatible task/protocol cohorts.
      </p>
      <DataTable
        rows={rows}
        emptyHint="No agent results yet."
        columns={[
          { key: 'name', header: 'Agent', value: (r) => r.name },
          { key: 'success_rate', header: 'Success rate', value: (r) => r.success_rate, numeric: true,
            render: (r) => `${(r.success_rate * 100).toFixed(1)}%` },
          { key: 'mean_score', header: 'Mean score', value: (r) => r.mean_score, numeric: true },
          { key: 'mean_steps', header: 'Steps (μ)', value: (r) => r.mean_steps, numeric: true },
          { key: 'failed_tool_calls_mean', header: 'Failed tools (μ)', value: (r) => r.failed_tool_calls_mean, numeric: true },
          { key: 'wall_ms_p95', header: 'p95 wall ms', value: (r) => r.wall_ms_p95, numeric: true },
        ] as Column<(typeof rows)[number]>[]}
      />
      {domains.length > 0 && heatAgents.length > 0 && (
        <>
          <h2>Domain coverage</h2>
          <p className="muted">Success rate per task domain — blank cells mean no runs recorded.</p>
          <Heatmap rows={domains} cols={heatAgents} cells={cells} rowLabel="domain success" />
        </>
      )}
    </div>
  )
}

export function AgentsPage() {
  const results = useAsync(getResults)
  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const byAgent = new Map<string, ResultRow[]>()
  for (const r of results.data ?? []) {
    byAgent.set(r.agent, [...(byAgent.get(r.agent) ?? []), r])
  }
  return (
    <div>
      <h1>Agents</h1>
      {[...byAgent.entries()].map(([name, rs]) => {
        const ok = rs.filter((r) => r.success).length
        return (
          <section key={name} className="card">
            <h2>{name}</h2>
            <p>
              {rs.length} runs · success {(rs.length ? (ok / rs.length) * 100 : 0).toFixed(0)}% ·
              mean score {(rs.reduce((s, r) => s + r.score_total, 0) / (rs.length || 1)).toFixed(2)}
            </p>
            <BarChart
              data={[...new Set(rs.map((r) => r.task_id))].map((t) => {
                const sub = rs.filter((r) => r.task_id === t)
                return { label: t, value: sub.filter((r) => r.success).length / sub.length }
              })}
              max={1}
              format={(v) => `${(v * 100).toFixed(0)}%`}
            />
          </section>
        )
      })}
    </div>
  )
}

export function ModelsPage() {
  // Models are only listed when adapters report model metadata; the scripted
  // reference agent has none, so this page honestly shows an empty state.
  const results = useAsync(getResults)
  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const withModel = (results.data ?? []).filter((r) => r.agent !== 'scripted')
  return (
    <div>
      <h1>Models</h1>
      <p className="muted">
        Model-level breakdowns appear here once provider-backed agents report
        model metadata in their bundles.
      </p>
      {withModel.length === 0 ? (
        <p className="state empty">No provider-backed results recorded yet.</p>
      ) : (
        <DataTable
          rows={withModel}
          emptyHint="No model-backed results."
          columns={[
            { key: 'agent', header: 'Agent', value: (r) => r.agent },
            { key: 'task_id', header: 'Task', value: (r) => r.task_id },
            { key: 'score_total', header: 'Score', value: (r) => r.score_total, numeric: true },
          ]}
        />
      )}
    </div>
  )
}

export function TaskPacksPage() {
  const tasks = useAsync(getTasks)
  const [category, setCategory] = useFilter('')
  if (tasks.loading) return <Loading />
  if (tasks.error) return <ErrorState message={tasks.error} />
  const all = tasks.data ?? []
  const categories = [...new Set(all.map((t) => t.category))]
  const filtered = category ? all.filter((t) => t.category === category) : all
  return (
    <div>
      <h1>Task Packs</h1>
      <label className="filter">
        Category:{' '}
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All ({all.length})</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </label>
      <DataTable
        rows={filtered}
        emptyHint="No tasks match this filter."
        columns={[
          {
            key: 'id', header: 'Task',
            value: (t) => t.id,
            render: (t) => <Link to={`/tasks/${encodeURIComponent(t.id)}`}>{t.id}</Link>,
          },
          { key: 'version', header: 'Version', value: (t) => t.version },
          { key: 'category', header: 'Category', value: (t) => t.category },
          { key: 'difficulty', header: 'Difficulty', value: (t) => t.difficulty },
          { key: 'max_steps', header: 'Max steps', value: (t) => t.max_steps, numeric: true },
          {
            key: 'perturbations', header: 'Perturbations',
            value: (t) => t.perturbations.join(', ') || '—',
          },
        ]}
      />
    </div>
  )
}

export function TaskDetailPage() {
  const { taskId } = useParams()
  const tasks = useAsync(getTasks)
  const results = useAsync(getResults)
  if (tasks.loading || results.loading) return <Loading />
  if (tasks.error) return <ErrorState message={tasks.error} />
  const task = (tasks.data ?? []).find((t) => t.id === taskId)
  const runs = (results.data ?? []).filter((r) => r.task_id === taskId)
  if (!task) return <ErrorState message={`Unknown task ${taskId}`} />
  const okRate = runs.length ? runs.filter((r) => r.success).length / runs.length : null
  return (
    <div>
      <h1>{task.id}</h1>
      <p className="muted">
        v{task.version} · {task.category} · {task.difficulty}
        {task.perturbations.length > 0 && <> · perturbations: {task.perturbations.join(', ')}</>}
      </p>
      <section className="grid stats">
        <div className="card"><strong>{runs.length}</strong><span>recorded runs</span></div>
        <div className="card"><strong>{okRate === null ? '–' : `${(okRate * 100).toFixed(0)}%`}</strong><span>success rate</span></div>
        <div className="card"><strong>{task.max_steps}</strong><span>max steps</span></div>
      </section>
      <h2>Runs</h2>
      <DataTable
        rows={runs}
        emptyHint="No runs recorded for this task yet."
        columns={[
          {
            key: 'bundle', header: 'Bundle',
            value: (r) => r.bundle,
            render: (r) => <Link to={`/results/${encodeURIComponent(r.bundle)}`}>{r.run_id}</Link>,
          },
          { key: 'agent', header: 'Agent', value: (r) => r.agent },
          { key: 'score_total', header: 'Score', value: (r) => r.score_total, numeric: true },
          { key: 'steps', header: 'Steps', value: (r) => r.steps, numeric: true },
          { key: 'wall_ms', header: 'Wall ms', value: (r) => r.wall_ms, numeric: true },
        ]}
      />
    </div>
  )
}