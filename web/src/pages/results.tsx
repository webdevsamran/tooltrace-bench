import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getResults, useAsync } from '../api'
import { LineChart } from '../charts'
import {
  BarChart, DataTable, DiffViewer, EmptyState, ErrorState,
  LineChart as LineChartOld, Loading, SuccessBadge, TraceTimeline,
} from '../components'
import type { TraceLine } from '../components'

// Fetch a bundle's trace + diff lazily from the raw-data directory.
async function fetchBundleDetail(bundle: string) {
  const base = `bundles/${bundle}`
  const [traceRes, diffRes] = await Promise.all([
    fetch(`${base}/trace.json`),
    fetch(`${base}/workspace.diff.txt`),
  ])
  const trace: TraceLine[] = traceRes.ok ? await traceRes.json() : []
  const diff = diffRes.ok ? await diffRes.text() : ''
  return { trace, diff }
}

export function ResultDetailPage() {
  const { bundle } = useParams()
  const results = useAsync(getResults)
  const detail = useAsync(
    () => (bundle ? fetchBundleDetail(bundle) : Promise.resolve({ trace: [], diff: '' })),
    [bundle],
  )
  if (results.loading || detail.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const row = (results.data ?? []).find((r) => r.bundle === bundle)
  if (!row) return <ErrorState message={`Unknown bundle ${bundle}`} />
  return (
    <div>
      <h1>Result <code>{row.run_id}</code></h1>
      <p className="muted">
        <Link to={`/tasks/${encodeURIComponent(row.task_id)}`}>{row.task_id}</Link> ·
        agent {row.agent} · trust {row.trust_state}
      </p>
      <section className="grid stats">
        <div className="card"><SuccessBadge ok={row.success} partial={row.partial_success} /><span>{row.failure_reason}</span></div>
        <div className="card"><strong>{row.score_total.toFixed(2)}</strong><span>score</span></div>
        <div className="card"><strong>{row.steps}</strong><span>steps</span></div>
        <div className="card"><strong>{row.tool_calls}</strong><span>tool calls ({row.failed_tool_calls} failed)</span></div>
        <div className="card"><strong>{row.wall_ms.toFixed(1)}</strong><span>wall ms</span></div>
      </section>
      <h2>Trace timeline</h2>
      <TraceTimeline events={detail.data?.trace ?? []} />
      <h2>Workspace diff</h2>
      <DiffViewer diff={detail.data?.diff ?? ''} />
    </div>
  )
}

export function ComparePage() {
  const results = useAsync(getResults)
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const rows = results.data ?? []
  const agents = [...new Set(rows.map((r) => r.agent))]
  type MetricKey = 'success' | 'score_total' | 'steps' | 'failed_tool_calls' | 'wall_ms'
  const metrics: { key: MetricKey; label: string; lowerBetter?: boolean }[] = [
    { key: 'success', label: 'Success rate' },
    { key: 'score_total', label: 'Mean score' },
    { key: 'steps', label: 'Mean steps', lowerBetter: true },
    { key: 'failed_tool_calls', label: 'Failed tool calls (μ)', lowerBetter: true },
    { key: 'wall_ms', label: 'p95 wall ms', lowerBetter: true },
  ]
  const statsFor = (agent: string) => {
    const rs = rows.filter((r) => r.agent === agent)
    const p95 = (xs: number[]) => {
      if (!xs.length) return 0
      const s = [...xs].sort((x, y) => x - y)
      return s[Math.min(s.length - 1, Math.floor(0.95 * s.length))]
    }
    return {
      success: rs.length ? rs.filter((r) => r.success).length / rs.length : 0,
      score_total: rs.reduce((s, r) => s + r.score_total, 0) / (rs.length || 1),
      steps: rs.reduce((s, r) => s + r.steps, 0) / (rs.length || 1),
      failed_tool_calls: rs.reduce((s, r) => s + r.failed_tool_calls, 0) / (rs.length || 1),
      wall_ms: p95(rs.map((r) => r.wall_ms)),
    }
  }
  return (
    <div>
      <h1>Compare</h1>
      <p className="muted">Aggregate comparison across agents on identical task/protocol versions.</p>
      <div className="compare-pickers">
        {agents.map((ag) => (
          <label key={ag}>
            <input type="checkbox" checked={a === ag || b === ag}
              onChange={(e) => {
                if (e.target.checked) { if (!a) setA(ag); else if (!b) setB(ag) }
                else { if (a === ag) setA(''); if (b === ag) setB('') }
              }} /> {ag}
          </label>
        ))}
      </div>
      {a && b ? (
        <table className="compare-table">
          <thead><tr><th>Metric</th><th>{a}</th><th>{b}</th><th>Better</th></tr></thead>
          <tbody>
            {metrics.map((m) => {
              const va: number = statsFor(a)[m.key]
              const vb: number = statsFor(b)[m.key]
              const better = m.lowerBetter ? (va <= vb ? a : b) : va >= vb ? a : b
              return (
                <tr key={String(m.key)}>
                  <td>{m.label}</td>
                  <td>{typeof va === 'number' && va <= 1 && m.key !== 'steps' && m.key !== 'wall_ms' && m.key !== 'failed_tool_calls' ? `${(va * 100).toFixed(1)}%` : va.toFixed(2)}</td>
                  <td>{typeof vb === 'number' && vb <= 1 && m.key !== 'steps' && m.key !== 'wall_ms' && m.key !== 'failed_tool_calls' ? `${(vb * 100).toFixed(1)}%` : vb.toFixed(2)}</td>
                  <td><strong>{better}</strong></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <EmptyState hint="Pick two agents to compare." />
      )}
    </div>
  )
}

export function ReliabilityTrendsPage() {
  const results = useAsync(getResults)
  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const rows = [...(results.data ?? [])].sort((x, y) => x.created_at.localeCompare(y.created_at))
  // Plain computation (no hook): this runs only on the loaded render path,
  // keeping hook order stable across loading/error/loaded states.
  const byAgent = (() => {
    const m = new Map<string, number[]>()
    for (const r of rows) m.set(r.agent, [...(m.get(r.agent) ?? []), r.success ? 1 : 0])
    return m
  })()
  return (
    <div>
      <h1>Reliability Trends</h1>
      <p className="muted">Rolling success over recorded runs (chronological).</p>
      {[...byAgent.entries()].map(([agent, pts]) => (
        <section key={agent}>
          <h2>{agent}</h2>
          <LineChartOld series={[{ label: 'success (1/0)', points: pts }]} />
          <h3>Running success probability</h3>
          <SuccessCurve agent={agent} outcomes={pts} />
          {pts.length >= 3 && (
            <>
              <h3>pass@k estimate</h3>
              <PassAtKCurve outcomes={pts} />
            </>
          )}
        </section>
      ))}
      {byAgent.size === 0 && <EmptyState hint="No runs recorded yet." />}
    </div>
  )
}

/** Running (cumulative) success probability per attempt — the empirical
 * foundation for pass^k-style consistency estimates. */
function SuccessCurve({ agent, outcomes }: { agent: string; outcomes: number[] }) {
  let successes = 0
  const points = outcomes.map((v, i) => {
    successes += v
    return { x: i + 1, y: successes / (i + 1) }
  })
  if (points.length === 0) return null
  return (
    <LineChart
      series={[{ name: `${agent} running pass rate`, points }]}
      xLabel="attempt"
      yLabel="pass rate"
      yMax={1}
    />
  )
}

/** Unbiased pass@k estimator over the recorded attempts:
 * pass@k = E[1 − C(n−c, k)/C(n, k)] with n attempts and c successes.
 * Small samples produce wide uncertainty — treat as indicative only. */
export function estimatePassAtK(outcomes: number[], maxK = 10): { x: number; y: number }[] {
  const n = outcomes.length
  const c = outcomes.reduce((a, b) => a + b, 0)
  const ks = Array.from({ length: Math.min(maxK, n) }, (_, i) => i + 1)
  return ks.map((k) => {
    let probAllFailWithinK = 1
    for (let i = 0; i < k; i++) probAllFailWithinK *= (n - c - i) / (n - i)
    return { x: k, y: 1 - probAllFailWithinK }
  })
}

function PassAtKCurve({ outcomes }: { outcomes: number[] }) {
  const points = estimatePassAtK(outcomes)
  if (points.length < 2) return null
  return (
    <LineChart
      series={[{ name: 'unbiased pass@k', points }]}
      xLabel="k (attempts drawn)"
      yLabel="pass@k"
      yMax={1}
    />
  )
}

export function FailureAnalysisPage() {
  const results = useAsync(getResults)
  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const rows = results.data ?? []
  const failures = rows.filter((r) => !r.success)
  const byReason = new Map<string, number>()
  for (const f of failures) byReason.set(f.failure_reason, (byReason.get(f.failure_reason) ?? 0) + 1)
  return (
    <div>
      <h1>Failure Analysis</h1>
      <BarChart
        data={[...byReason.entries()].map(([label, value]) => ({ label, value }))}
        format={(v) => String(v)}
      />
      <h2>Failed runs</h2>
      <DataTable
        rows={failures}
        emptyHint="No failures recorded — nothing to analyze."
        columns={[
          { key: 'task_id', header: 'Task', value: (r) => r.task_id },
          { key: 'agent', header: 'Agent', value: (r) => r.agent },
          { key: 'failure_reason', header: 'Category', value: (r) => r.failure_reason },
          { key: 'score_total', header: 'Score', value: (r) => r.score_total, numeric: true },
          { key: 'failed_tool_calls', header: 'Failed tools', value: (r) => r.failed_tool_calls, numeric: true },
        ]}
      />
    </div>
  )
}