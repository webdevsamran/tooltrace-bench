import { Link, useParams } from 'react-router-dom'
import { assetUrl, getResults, useAsync } from '../api'
import { LineChart } from '../charts'
import { estimatePassAtK } from '../lib/passAtK'
import {
  DiffViewer, EmptyState, ErrorState,
  LineChart as LineChartOld, Loading, SuccessBadge, TraceTimeline,
} from '../components'
import type { TraceLine } from '../components'
import { useUrlState } from '../lib/useUrlState'
import { clusterFailures, stepLink } from '../lib/clusters'

// Fetch a bundle's trace + diff lazily from the raw-data directory.
async function fetchBundleDetail(bundle: string) {
  // assetUrl, not a bare relative string: this page *is* a nested route, so a
  // relative fetch here asks for `/results/bundles/...` and always 404s.
  const base = assetUrl(`bundles/${bundle}`)
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
  // Arriving from a failure cluster carries the step in the URL, so the link
  // is the whole navigation: no scrolling, no searching for the failure.
  // Called before the early returns below to keep hook order stable.
  const [seqParam] = useUrlState('seq')
  if (results.loading || detail.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const row = (results.data ?? []).find((r) => r.bundle === bundle)
  if (!row) return <ErrorState message={`Unknown bundle ${bundle}`} />
  const step = row.failure_step ?? null
  // The URL wins when present -- someone may have linked to a step other than
  // the attributed one -- and a non-numeric parameter highlights nothing
  // rather than throwing.
  const parsed = Number.parseInt(seqParam, 10)
  const highlightSeq = Number.isFinite(parsed) ? parsed : (step?.seq ?? null)
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
      {step && (
        <p className="callout callout-bad">
          <strong>Failure attributed to step {step.seq === null ? '(unattributed)' : `#${step.seq}`}</strong>
          {step.tool && <> · <code>{step.tool}</code></>} · rule <code>{step.rule}</code>
          {step.detail && <> — {step.detail}</>}
        </p>
      )}
      <h2>Trace timeline</h2>
      <TraceTimeline events={detail.data?.trace ?? []} highlightSeq={highlightSeq} />
      <h2>Workspace diff</h2>
      <DiffViewer diff={detail.data?.diff ?? ''} />
    </div>
  )
}

export function ComparePage() {
  const results = useAsync(getResults)
  // In the URL so a comparison is a link. Previously these lived in component
  // state only, so "look at this comparison" meant describing which two
  // agents to pick, and a reload lost the selection.
  const [a, setA] = useUrlState('a')
  const [b, setB] = useUrlState('b')
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


/**
 * The failure-cluster explorer.
 *
 * What was here before was a dropdown and a bar chart of failure *categories*.
 * That view can tell you eleven runs hit `execution` and cannot tell you
 * whether that is one bug or eleven — and it left the reader to find the
 * relevant step in a trace by hand afterwards.
 *
 * This clusters on the failure signature instead (reason + the rule that
 * matched + the tool it was attributed to) and every run in a cluster links
 * straight to the step that broke. The chain is: cluster → run → step.
 */
export function FailureAnalysisPage() {
  const results = useAsync(getResults)
  const [selected, setSelected] = useUrlState('cluster')
  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />

  const rows = results.data ?? []
  const clusters = clusterFailures(rows)
  const failures = rows.filter((r) => !r.success)
  const open = clusters.find((c) => c.id === selected) ?? null
  // How much of the failure set is openable at a step. Stated plainly, because
  // a reader who clicks three clusters and finds no step links deserves to
  // know that up front rather than infer it.
  const attributed = failures.filter((f) => typeof f.failure_step?.seq === 'number').length

  return (
    <div>
      <h1>Failure clusters</h1>
      <p className="muted">
        Failed runs grouped by signature — the failure class, the rule that matched, and the
        tool call it was attributed to. Runs that share a signature are usually one defect;
        the same class reached by different rules usually is not.
      </p>

      {failures.length === 0 ? (
        <EmptyState hint="No failed runs in this dataset — there is nothing to cluster." />
      ) : (
        <>
          <section className="stats" aria-label="Failure summary">
            <div className="stat">
              <span className="stat-label">Failed runs</span>
              <span className="stat-value">{failures.length}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Clusters</span>
              <span className="stat-value">{clusters.length}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Attributed to a step</span>
              <span className="stat-value">
                {attributed} / {failures.length}
              </span>
            </div>
          </section>

          <div className="cluster-layout">
            <section aria-label="Clusters">
              <h2>Clusters</h2>
              <ul className="cluster-list">
                {clusters.map((c) => (
                  <li key={c.id}>
                    <button
                      type="button"
                      className={`cluster-card${c.id === selected ? ' is-open' : ''}`}
                      aria-expanded={c.id === selected}
                      aria-controls="cluster-detail"
                      onClick={() => setSelected(c.id === selected ? '' : c.id)}
                    >
                      <span className="cluster-count">{c.runs.length}</span>
                      <span className="cluster-body">
                        <strong>{c.reason}</strong>
                        <code className="cluster-rule">{c.rule}</code>
                        {c.tool && <code className="cluster-tool">{c.tool}</code>}
                        <span className="cluster-meta">
                          {c.tasks.length} task{c.tasks.length === 1 ? '' : 's'} ·{' '}
                          {c.agents.length} agent{c.agents.length === 1 ? '' : 's'}
                          {c.representativeSeq !== null && ` · every run at step #${c.representativeSeq}`}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>

            <section id="cluster-detail" aria-label="Cluster detail" aria-live="polite">
              <h2>{open ? 'Runs in this cluster' : 'Pick a cluster'}</h2>
              {open ? (
                <>
                  {open.detail && <p className="cluster-detail-text">{open.detail}</p>}
                  <p className="muted">
                    Spanning {open.tasks.join(', ')} across {open.agents.join(', ')}.
                  </p>
                  <ul className="cluster-runs">
                    {open.runs.map((r) => (
                      <li key={r.bundle}>
                        <Link to={stepLink(r)}>
                          <code>{r.task_id}</code>
                          {typeof r.failure_step?.seq === 'number' ? (
                            <span className="run-step">open at step #{r.failure_step.seq}</span>
                          ) : (
                            <span className="run-step muted">no step attributed</span>
                          )}
                        </Link>
                        <span className="muted"> {r.agent} · score {r.score_total.toFixed(2)}</span>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <EmptyState hint="Select a cluster to see its runs and jump to the failing step." />
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}
