import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Counter } from '../motion'
import {
  BrushControls,
  describeBrush,
  isEmptyRange,
  withinBrush,
  type BrushRange,
} from '../brush'
import {
  assetUrl,
  getIndex,
  getPareto,
  getResults,
  useAsync,
  type IndexData,
  type ParetoPoint,
  type ResultRow,
} from '../api'
import {
  DataTable,
  DiffViewer,
  EmptyState,
  ErrorState,
  Loading,
  VirtualList,
  type Column,
} from '../components'
import { Histogram, ParetoChart, Scatter } from '../charts'
import { useUrlState } from '../lib/useUrlState'

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

type TraceView = 'all' | 'tools' | 'assertions'

/** Trace Explorer: filterable timeline with expandable sanitized payloads,
 * jump-to-assertion and workspace-diff views. Large traces are windowed via
 * VirtualList so multi-thousand-event runs scroll smoothly instead of
 * freezing the browser tab. */
export function TraceExplorerPage() {
  const results = useAsync(getResults)
  const [selected, setSelected] = useState<string | null>(null)
  const [events, setEvents] = useState<TraceEvent[] | null>(null)
  const [traceError, setTraceError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [openEvent, setOpenEvent] = useState<number | null>(null)
  const [view, setView] = useState<TraceView>('all')
  const [diffText, setDiffText] = useState<string | null>(null)

  useEffect(() => {
    if (!selected) return
    setOpenEvent(null)
    setEvents(null)
    setTraceError(null)
    setDiffText(null)
    // These asked for `trace.jsonl` and `workspace.diff` -- the names inside a
    // .tooltrace bundle. `scripts/generate_web_data.py` publishes them as
    // `trace.json` (a JSON array) and `workspace.diff.txt`, so every fetch here
    // 404'd and the Trace Explorer had never displayed a trace at all. The
    // published names are the contract; the names inside the bundle are not.
    fetch(assetUrl(`bundles/${selected}/trace.json`))
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((events) => setEvents(events as TraceEvent[]))
      .catch((e) => setTraceError(String(e)))
    // Workspace diff is optional bundle content; absence is not an error.
    fetch(assetUrl(`bundles/${selected}/workspace.diff.txt`))
      .then((r) => (r.ok ? r.text() : ''))
      .then((text) => setDiffText(text || null))
      .catch(() => setDiffText(null))
  }, [selected])

  const filtered = useMemo(
    () =>
      (events ?? []).filter((e) => {
        if (view === 'tools' && e.type !== 'tool_call' && e.type !== 'tool_result') return false
        if (view === 'assertions' && e.type !== 'validation') return false
        if (!filter) return true
        return JSON.stringify(e).toLowerCase().includes(filter.toLowerCase())
      }),
    [events, filter, view],
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
          <div className="trace-toolbar" role="toolbar" aria-label="Trace view mode">
            <label className="field">
              View{' '}
              <select value={view} onChange={(e) => setView(e.target.value as TraceView)}>
                <option value="all">All events</option>
                <option value="tools">Tool calls</option>
                <option value="assertions">Assertions only (jump-to-assertion)</option>
              </select>
            </label>
            <input
              className="search"
              type="search"
              placeholder="Filter events by type, tool or status…"
              aria-label="Filter trace events"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          {traceError && <ErrorState message={traceError} />}
          {!events && !traceError && <Loading />}
          {events && (
            <>
              {/* The count rolls, because it is a number that changes as a
                  result of what you just typed -- which is the only place a
                  rolling counter earns its 200ms. The accessible text is the
                  settled value, never the animating one; see `motion.tsx`. */}
              <p className="muted" role="status" aria-live="polite" aria-label="Matching events">
                <Counter value={filtered.length} /> of {events.length} event
                {events.length === 1 ? '' : 's'}
                {filter ? ' match the filter' : ''}
              </p>
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
              {view === 'all' && diffText !== null && (
                <details className="card" open={Boolean(diffText)}>
                  <summary>Workspace diff {diffText ? '' : '(none recorded)'}</summary>
                  <DiffViewer diff={diffText} />
                </details>
              )}
              <p>
                {/* Same correction as the fetch above: the published file is
                    trace.json, and the link needs the site base or it points
                    at a path relative to whatever route the reader is on. */}
                <a href={assetUrl(`bundles/${selected}/trace.json`)} download>
                  Download raw trace
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
/**
 * Where the wall time went: thinking, doing, or the harness.
 *
 * `model_ms` and `tool_ms` were on every result row and nothing had ever shown
 * them together, so the page could tell you a run took 40 ms and not whether the
 * agent was slow at deciding or slow at acting — which is the first question
 * anyone optimising an agent has.
 *
 * `model_ms` is null whenever the adapter cannot report it (the scripted agent
 * has no model at all). In that case the harness share stays *unknown* rather
 * than being computed as the remainder: a number derived from an unmeasured
 * input is invention, and it would land in the one place a reader would trust it.
 */
function LatencySplit({ rows }: { rows: ResultRow[] }) {
  const withModel = rows.filter((r) => r.model_ms != null)
  const total = (pick: (r: ResultRow) => number) => rows.reduce((a, r) => a + pick(r), 0)
  const wall = total((r) => r.wall_ms)
  const tool = total((r) => r.tool_ms)
  const model = withModel.reduce((a, r) => a + (r.model_ms ?? 0), 0)

  if (wall <= 0) return null
  const toolShare = tool / wall
  const modelKnown = withModel.length === rows.length && rows.length > 0

  return (
    <section>
      <h2>Where the time goes</h2>
      {modelKnown ? (
        <p className="muted">
          Inference against tool execution across {rows.length} run
          {rows.length === 1 ? '' : 's'}. The remainder is harness overhead.
        </p>
      ) : (
        <p className="callout callout-warn">
          <strong>
            {withModel.length} of {rows.length} runs report inference time.
          </strong>{' '}
          Adapters that cannot separate model time leave it unmeasured, so the harness share is
          unknown rather than the remainder — a figure derived from an unmeasured input would look
          like a measurement.
        </p>
      )}
      <div className="split-bar" role="img"
        aria-label={
          modelKnown
            ? `Inference ${(model / wall * 100).toFixed(0)} percent, tools ${(toolShare * 100).toFixed(0)} percent of wall time`
            : `Tools ${(toolShare * 100).toFixed(0)} percent of wall time; inference time not reported`
        }
      >
        {modelKnown && (
          <span className="split-model" style={{ width: `${(model / wall) * 100}%` }} />
        )}
        <span className="split-tool" style={{ width: `${toolShare * 100}%` }} />
      </div>
      <dl className="kv">
        <dt>Tool execution</dt>
        <dd>
          {tool.toFixed(1)} ms ({(toolShare * 100).toFixed(1)}%)
        </dd>
        <dt>Inference</dt>
        <dd>
          {modelKnown ? `${model.toFixed(1)} ms (${((model / wall) * 100).toFixed(1)}%)` : 'not reported by this adapter'}
        </dd>
        <dt>Harness overhead</dt>
        <dd>
          {modelKnown
            ? `${Math.max(0, wall - model - tool).toFixed(1)} ms`
            : 'unknown while inference time is unreported'}
        </dd>
      </dl>
    </section>
  )
}

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
      <LatencySplit rows={eff.rows} />

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
/**
 * The cost/accuracy frontier: which agents nobody beats on both axes at once.
 *
 * `pareto_frontier` shipped in `tooltrace/metrics/economics.py` with no caller
 * outside its own tests, so the question it answers could be computed and was
 * never asked. This is the asking.
 *
 * The page is deliberately loud about what it cannot draw. An agent whose runs
 * reported no spend has an unmeasured axis, not a cost of zero -- treating it as
 * free would put it on the frontier by default and make the chart actively
 * misleading. Those agents are listed by name instead, above the chart, so a
 * reader sees the gap rather than a plot that looks complete.
 */
export function ParetoExplorerPage() {
  const pareto = useAsync(getPareto)
  const [selected, setSelected] = useUrlState('agent')
  const [brush, setBrush] = useState<BrushRange | null>(null)

  if (pareto.loading) return <Loading />
  if (pareto.error) return <ErrorState message={pareto.error} />
  const data = pareto.data
  if (!data) return <ErrorState message="no frontier data" />

  const priced = data.points.filter((p) => p.cost_per_resolved_task !== null)
  const focus = data.points.find((p) => p.agent === selected) ?? null

  const costs = priced.map((p) => p.cost_per_resolved_task as number)
  const bounds: BrushRange = {
    x0: 0,
    x1: Math.max(...costs, 0),
    y0: 0,
    y1: 1,
  }
  const inRange = priced.filter((p) =>
    withinBrush({ x: p.cost_per_resolved_task as number, y: p.success_rate }, brush),
  )

  return (
    <section>
      <h1>Cost–accuracy frontier</h1>
      <p className="muted">
        An agent is <strong>dominated</strong> when another is at least as accurate and at least as
        cheap, and strictly better on one of them. What is left is the frontier: the set where
        buying more accuracy costs more money, and no choice is simply worse than another.
      </p>

      {data.unpriced.length > 0 && (
        <div className="notice" role="note">
          <strong>{data.unpriced.length} agent(s) have no measured cost</strong> and are not on the
          chart: {data.unpriced.join(', ')}. An unpriced run has an unmeasured axis, not a cost of
          zero. Treating it as free would place it on the frontier by default.
        </div>
      )}

      {priced.length === 0 ? (
        <EmptyState hint="No run in this dataset reported spend, so there is no frontier to draw. Cost is recorded only when an adapter reports token usage and a dated price table covers the model." />
      ) : priced.length === 1 ? (
        <EmptyState hint={`Only ${priced[0].agent} has a measured cost. A frontier drawn from one agent names that agent and means nothing.`} />
      ) : (
        <>
          <ParetoChart
            points={data.points}
            frontier={data.frontier}
            selected={selected || null}
            onSelect={(agent) => setSelected(agent ?? '')}
            brush={brush}
            onBrush={setBrush}
          />
          {/* Drag on the chart, or type the range. The second is not a
              consolation: a filter reachable only by drag is a filter a
              keyboard user does not have, and axe gates this build. */}
          <BrushControls
            brush={brush}
            bounds={bounds}
            onChange={setBrush}
            xLabel="cost"
            yLabel="accuracy"
            xStep={0.001}
          />
          {/* The brushed set is *named*, never quietly removed from the chart.
              A reader looking at a subset that believed it was the whole is the
              same defect as a shard's rate read as a sweep's. */}
          {/* Named, because the toast region is also a live region: a reader
              hearing an unattributed announcement cannot tell which part of the
              page spoke. */}
          <p className="muted" role="status" aria-live="polite" aria-label="Selected range">
            {describeBrush(inRange.length, priced.length, brush)}
            {!isEmptyRange(brush) && inRange.length > 0 && (
              <> In range: {inRange.map((p) => p.agent).join(', ')}.</>
            )}
          </p>
          <p className="muted">{data.statement}</p>
        </>
      )}

      {focus && (
        <div className="panel" aria-live="polite">
          <h2>{focus.agent}</h2>
          <p>
            {data.frontier.includes(focus.agent)
              ? 'On the frontier: no other agent here is both at least as accurate and at least as cheap.'
              : 'Dominated: another agent here is at least as accurate and at least as cheap.'}
          </p>
          <div className="stats">
            <Stat label="Success rate" value={`${(focus.success_rate * 100).toFixed(1)}%`} />
            <Stat
              label="Cost per resolved task"
              value={focus.cost_per_resolved_task === null ? 'unmeasured' : String(focus.cost_per_resolved_task)}
            />
            <Stat label="Runs" value={String(focus.runs)} />
            <Stat label="Priced runs" value={`${focus.priced_runs} of ${focus.runs}`} />
          </div>
        </div>
      )}

      <h2>Every agent</h2>
      <DataTable<ParetoPoint>
        rows={data.points}
        emptyHint="No agent has been measured yet."
        columns={[
          { key: 'agent', header: 'Agent', value: (p) => p.agent },
          {
            key: 'position',
            header: 'Position',
            value: (p) =>
              p.cost_per_resolved_task === null
                ? 'unpriced'
                : data.frontier.includes(p.agent)
                  ? 'frontier'
                  : 'dominated',
          },
          {
            key: 'success_rate',
            header: 'Success rate',
            value: (p) => p.success_rate,
            render: (p) => `${(p.success_rate * 100).toFixed(1)}%`,
            numeric: true,
          },
          {
            key: 'cost',
            header: 'Cost / resolved task',
            // Sorted on a number, rendered as an em dash when unmeasured. An
            // unpriced agent sorting as 0 would sit at the cheap end of the
            // table, which is the same lie the chart refuses to tell.
            value: (p) => (p.cost_per_resolved_task === null ? Infinity : p.cost_per_resolved_task),
            render: (p) =>
              p.cost_per_resolved_task === null ? '—' : String(p.cost_per_resolved_task),
            numeric: true,
          },
          {
            key: 'priced_runs',
            header: 'Priced runs',
            value: (p) => p.priced_runs,
            render: (p) => `${p.priced_runs} / ${p.runs}`,
            numeric: true,
          },
        ]}
      />
    </section>
  )
}
