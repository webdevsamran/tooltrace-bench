import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getIndex, getResults, useAsync, type IndexData, type ResultRow } from '../api'
import { DataTable, ErrorState, Loading, VirtualList, type Column } from '../components'
import { Histogram, Scatter } from '../charts'

/** Bucket wall times into 5 roughly-even bins for the latency histogram. */
function latencyBins(values: number[]): { bins: number[]; labels: string[] } {
  if (values.length === 0) return { bins: [0, 0, 0, 0, 0], labels: ['–', '–', '–', '–', '–'] }
  const sorted = [...values].sort((a, b) => a - b)
  const min = sorted[0]
  const max = sorted[sorted.length - 1]
  const width = (max - min || min || 1) / 5
  const bins = [0, 0, 0, 0, 0]
  for (const v of values) {
    const idx = Math.min(4, Math.floor((v - min) / (width || 1)))
    bins[idx] += 1
  }
  return {
    bins,
    labels: Array.from({ length: 5 }, (_, i) =>
      `${Math.round(min + i * width)}–${Math.round(min + (i + 1) * width)}`,
    ),
  }
}

interface TraceEvent {
  seq?: number
  type?: string
  payload?: Record<string, unknown>
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  )
}

/** Trace Explorer: filterable timeline with expandable sanitized payloads.
 * Large traces are windowed via VirtualList so multi-thousand-event runs
 * scroll smoothly instead of freezing the browser tab. */
export function TraceExplorerPage() {
  const results = useAsync(getResults)
  const [selected, setSelected] = useState<string | null>(null)
  const [events, setEvents] = useState<TraceEvent[] | null>(null)
  const [traceError, setTraceError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [openEvent, setOpenEvent] = useState<number | null>(null)

  useEffect(() => {
    if (!selected) return
    setOpenEvent(null)
    setEvents(null)
    setTraceError(null)
    fetch(`bundles/${selected}/trace.jsonl`)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((text) =>
        setEvents(
          text
            .split('\n')
            .filter((l) => l.trim())
            .map((l) => JSON.parse(l) as TraceEvent),
        ),
      )
      .catch((e) => setTraceError(String(e)))
  }, [selected])

  const filtered = useMemo(
    () =>
      (events ?? []).filter((e) => {
        if (!filter) return true
        return JSON.stringify(e).toLowerCase().includes(filter.toLowerCase())
      }),
    [events, filter],
  )

  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />
  const rows = results.data ?? []

  return (
    <section>
      <h1>Trace Explorer</h1>
      <p className="muted">
        Inspect exactly why a run succeeded or failed: every event, tool call and validation,
        streamed line-by-line from the bundle trace. Long traces are virtualized — only visible
        events render.
      </p>
      <label className="field">
        Bundle{' '}
        <select value={selected ?? ''} onChange={(e) => setSelected(e.target.value || null)}>
          <option value="">— select a bundle —</option>
          {rows.map((r: ResultRow) => (
            <option key={r.bundle} value={r.bundle}>
              {r.run_id} ({r.task_id}, {r.success ? 'pass' : 'fail'})
            </option>
          ))}
        </select>
      </label>
      {selected && (
        <>
          <input
            className="search"
            type="search"
            placeholder="Filter events by type, tool or status…"
            aria-label="Filter trace events"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {traceError && <ErrorState message={traceError} />}
          {!events && !traceError && <Loading />}
          {events && (
            <>
              {filtered.length === 0 ? (
                <p className="state empty">No events match the filter.</p>
              ) : (
                <VirtualList
                  items={filtered}
                  itemHeight={44}
                  height={420}
                  ariaLabel="Trace events"
                  render={(e, i) => (
                    <button
                      type="button"
                      className={`trace-row${openEvent === i ? ' active' : ''}`}
                      onClick={() => setOpenEvent(openEvent === i ? null : i)}
                    >
                      <code>#{e.seq ?? i}</code> <strong>{e.type}</strong>
                      {'tool' in (e.payload ?? {}) && (
                        <span className="tag">{String(e.payload?.tool)}</span>
                      )}
                      {'status' in (e.payload ?? {}) && (
                        <span className={`tag ${e.payload?.status === 'ok' ? 'ok' : 'bad'}`}>
                          {String(e.payload?.status)}
                        </span>
                      )}
                    </button>
                  )}
                />
              )}
              {openEvent !== null && filtered[openEvent] && (
                <div className="card">
                  <strong>Event #{filtered[openEvent].seq ?? openEvent} — {filtered[openEvent].type}</strong>
                  <pre>{JSON.stringify(filtered[openEvent].payload ?? {}, null, 2)}</pre>
                </div>
              )}
              <p>
                <a href={`bundles/${selected}/trace.jsonl`} download>
                  Download raw JSONL trace
                </a>
              </p>
            </>
          )}
        </>
      )}
      {!selected && <p className="state empty">Select a bundle to load its trace.</p>}
    </section>
  )
}

interface RecoveryRow {
  task: string
  rate: number
  total: number
}

const recoveryColumns: Column<RecoveryRow>[] = [
  {
    key: 'task',
    header: 'Task',
    value: (r) => r.task,
    render: (r) => <Link to={`/tasks/${encodeURIComponent(r.task)}`}>{r.task}</Link>,
  },
  { key: 'rate', header: 'Recovery rate', value: (r) => r.rate, render: (r) => `${Math.round(r.rate * 100)}%`, numeric: true },
  { key: 'total', header: 'Runs', value: (r) => r.total, numeric: true },
]

/** Recovery Analysis: success despite failed/perturbed tool calls. */
export function RecoveryAnalysisPage() {
  const results = useAsync(getResults)
  const recovery = useMemo(() => {
    const rows = results.data ?? []
    const perturbed = rows.filter((r) => r.failed_tool_calls > 0)
    const recovered = perturbed.filter((r) => r.success)
    const byTask = new Map<string, { total: number; recovered: number }>()
    for (const r of perturbed) {
      const e = byTask.get(r.task_id) ?? { total: 0, recovered: 0 }
      e.total += 1
      if (r.success) e.recovered += 1
      byTask.set(r.task_id, e)
    }
    return {
      perturbedCount: perturbed.length,
      rate: perturbed.length ? recovered.length / perturbed.length : null,
      rows: [...byTask.entries()].map(([task, v]) => ({ task, rate: v.recovered / v.total, total: v.total })),
    }
  }, [results.data])

  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />

  return (
    <section>
      <h1>Recovery Analysis</h1>
      <p className="muted">
        Of runs that hit at least one failed tool call, how many still reached a correct final
        state? Recovery is measured per task family.
      </p>
      <div className="stats">
        <Stat label="Runs with failed tool calls" value={String(recovery.perturbedCount)} />
        <Stat label="Recovery rate" value={recovery.rate === null ? 'n/a' : `${Math.round(recovery.rate * 100)}%`} />
      </div>
      <DataTable columns={recoveryColumns} rows={recovery.rows} emptyHint="No runs with failed tool calls yet." />
    </section>
  )
}

/** Cost/Latency/Efficiency: outcome per step, per tool call, per ms. */
export function CostEfficiencyPage() {
  const results = useAsync(getResults)
  const eff = useMemo(() => {
    const rows = results.data ?? []
    const ok = rows.filter((r) => r.success)
    const mean = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)
    return {
      meanSteps: mean(ok.map((r) => r.steps)),
      meanToolCalls: mean(ok.map((r) => r.tool_calls)),
      wallMsMean: mean(rows.map((r) => r.wall_ms)),
      wastedCalls: rows.reduce((a, r) => a + r.repeated_calls + r.failed_tool_calls, 0),
      maxWall: Math.max(1, ...rows.map((r) => r.wall_ms)),
      rows,
    }
  }, [results.data])

  if (results.loading) return <Loading />
  if (results.error) return <ErrorState message={results.error} />

  return (
    <section>
      <h1>Cost · Latency · Efficiency</h1>
      <p className="muted">
        Trajectory efficiency: successful outcomes per step, per tool call and per unit wall time.
        Benchmark-side waiting is excluded where distinguishable.
      </p>
      <div className="stats">
        <Stat label="Mean steps (successful)" value={eff.meanSteps.toFixed(2)} />
        <Stat label="Mean tool calls (successful)" value={eff.meanToolCalls.toFixed(2)} />
        <Stat label="Mean wall time (ms)" value={eff.wallMsMean.toFixed(1)} />
        <Stat label="Wasted tool calls" value={String(eff.wastedCalls)} />
      </div>
      <h2>Score vs wall time</h2>
      <Scatter
        points={eff.rows.map((r) => ({ x: r.wall_ms, y: r.score_total, label: `${r.run_id} (${r.agent})` }))}
        xLabel="wall time (ms)"
        yLabel="score"
        height={200}
      />
      <h2>Latency distribution</h2>
      <Histogram
        bins={latencyBins(eff.rows.map((r) => r.wall_ms)).bins}
        labels={latencyBins(eff.rows.map((r) => r.wall_ms)).labels}
        xLabel="wall ms buckets"
      />
      <h2>Wall time per run</h2>
      <ul className="bars" aria-label="Wall time per run">
        {[...eff.rows]
          .sort((a, b) => b.wall_ms - a.wall_ms)
          .slice(0, 15)
          .map((r) => (
            <li key={r.run_id}>
              <span className="bar-label">{r.run_id}</span>
              <span
                className="bar"
                style={{ width: `${(r.wall_ms / eff.maxWall) * 100}%` }}
                role="img"
                aria-label={`${r.wall_ms.toFixed(1)} ms`}
              />
              <span className="bar-value">{r.wall_ms.toFixed(1)} ms</span>
            </li>
          ))}
      </ul>
    </section>
  )
}

/** Dataset/Snapshot browser: validated dataset statistics and provenance. */
export function DatasetBrowserPage() {
  const index = useAsync(getIndex)
  if (index.loading) return <Loading />
  if (index.error) return <ErrorState message={index.error} />
  const data = index.data as IndexData | null
  if (!data) return <EmptyStateOrError />
  return (
    <section>
      <h1>Dataset & Snapshots</h1>
      <p className="muted">
        Public data is generated only from validated repository bundles. Every snapshot carries a
        changelog, file counts and SHA-256 hashes (<code>tooltrace snapshot</code>).
      </p>
      <dl className="kv">
        <dt>Generated at</dt>
        <dd>{data.generated_at}</dd>
        <dt>Framework version</dt>
        <dd>{data.framework_version}</dd>
        <dt>Compatibility key</dt>
        <dd><code>{data.compatibility_key}</code></dd>
      </dl>
      <div className="stats">
        <Stat label="Tasks" value={String(data.counts.tasks)} />
        <Stat label="Results" value={String(data.counts.results)} />
        <Stat label="Agents" value={String(data.counts.agents)} />
        <Stat label="Packs" value={String(data.counts.packs)} />
      </div>
      <p>
        Regenerate locally: <code>python scripts/generate_web_data.py</code>, then{' '}
        <code>tooltrace snapshot --source web/public/data --output snapshot.json --changelog "…"</code>
      </p>
    </section>
  )
}

function EmptyStateOrError() {
  return <ErrorState message="Dataset index unavailable." />
}

const EXTENSION_POINTS = [
  ['Agent adapters', 'tooltrace.agents', 'OpenAI-compatible, Anthropic-compatible, Gemini-compatible and local subprocess adapters with capability negotiation.'],
  ['Tools', 'tooltrace.tools', 'Sandboxed tools agents may call; capability-negotiated per adapter.'],
  ['Scorers', 'tooltrace.scoring', 'Deterministic assertion scorers plus optional model judges with disagreement reporting.'],
  ['Exporters', 'tooltrace.exporters', 'Report formats (JSON/CSV/MD/JUnit/HTML) and custom exporter plugins.'],
  ['Task packs', 'examples/example-pack', 'Versioned packs with provenance manifests, lint rules and dry-run support.'],
]

/** Plugin Catalog: extension points without auto-installing remote code. */
export function PluginCatalogPage() {
  return (
    <section>
      <h1>Plugin Catalog</h1>
      <p className="muted">
        Extension points are semantic-versioned with compatibility ranges and conformance tests.
        Remote code is never installed automatically — always explicit user action.
      </p>
      <table>
        <caption>Extension points</caption>
        <thead>
          <tr><th scope="col">Area</th><th scope="col">Module / entry point</th><th scope="col">Description</th></tr>
        </thead>
        <tbody>
          {EXTENSION_POINTS.map(([area, mod, desc]) => (
            <tr key={area}>
              <th scope="row">{area}</th>
              <td><code>{mod}</code></td>
              <td>{desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        See <Link to="/docs">Docs</Link> and <code>CONTRIBUTING.md</code>. Scaffold a pack:{' '}
        <code>tooltrace task scaffold --pack-dir my-pack --task-id my-task</code>.
      </p>
    </section>
  )
}