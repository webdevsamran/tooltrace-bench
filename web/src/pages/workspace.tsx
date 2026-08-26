// Self-hosted team/enterprise console (part 1): server gate, workspace
// dashboard, experiments + builder + live monitor, workers, system health.
// In static mode every page offers an explicitly-labeled DEMO preview.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  apiPost, fetchHealth, getServerUrl, isServerMode, listExperiments,
  setServerToken, setServerUrl, subscribeEvents,
  type ExperimentRow,
} from '../api'
import { DataTable, DemoBadge, EmptyState, ErrorState, Loading, NoPermission, type Column } from '../components'
import { Ring } from '../charts'
import { DEMO_EXPERIMENTS, DEMO_WORKERS, type DemoWorker } from './demoData'

/** Gate shown when no self-hosted server is configured. */
export function ServerGate({ children }: { children: React.ReactNode }) {
  const [demo, setDemo] = useState(false)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')

  if (isServerMode() || demo) return <>{children}</>
  return (
    <div className="state" data-testid="server-gate">
      <h2>Connect to a ToolTrace server</h2>
      <p className="muted">
        These pages manage a self-hosted coordinator (<code>tooltrace server</code>). Connect to
        your deployment, or preview the console with clearly-labeled demo fixtures.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setServerUrl(url.trim())
          setServerToken(token.trim())
        }}
      >
        <label className="field">Server URL{' '}
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://localhost:8471" />
        </label>
        <label className="field">API token (optional){' '}
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="ttb_…" autoComplete="off" />
        </label>
        <button className="btn" type="submit">Connect</button>{' '}
        <button className="btn ghost" type="button" onClick={() => setDemo(true)}>Preview with DEMO data</button>
      </form>
    </div>
  )
}

/** Connection badge: DEMO marker in static mode, server URL otherwise.
 * Exported for the other workspace console modules. */
export function ServerStatus() {
  if (!isServerMode()) return <DemoBadge />
  return <span className="badge badge-info">{getServerUrl()}</span>
}
// ---------- workspace dashboard ----------

const WORKSPACE_SECTIONS = [
  ['Experiments', '/workspace/experiments'],
  ['Experiment builder', '/workspace/experiments/new'],
  ['Workers & capacity', '/workspace/workers'],
  ['Baselines & regressions', '/workspace/baselines'],
  ['Task Authoring Studio', '/workspace/studio'],
  ['Publication queue', '/workspace/reviews'],
  ['Users & service accounts', '/workspace/users'],
  ['Policies & budgets', '/workspace/policies'],
  ['Audit log', '/workspace/audit'],
  ['Webhooks', '/workspace/webhooks'],
  ['Retention & settings', '/workspace/settings'],
  ['System health', '/workspace/health'],
] as const

export function WorkspaceDashboardPage() {
  return (
    <section>
      <h1>Workspace</h1>
      <p><ServerStatus /> <span className="muted">Team collaboration on your own infrastructure.</span></p>
      <nav aria-label="Workspace sections" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '.6rem' }}>
        {WORKSPACE_SECTIONS.map(([label, to]) => (
          <Link key={to} className="card" to={to} style={{ textDecoration: 'none', color: 'inherit' }}>
            <strong style={{ fontSize: '.95rem' }}>{label}</strong>
          </Link>
        ))}
      </nav>
    </section>
  )
}

// ---------- experiments ----------

const EXP_COLS: Column<ExperimentRow>[] = [
  { key: 'id', header: 'ID', value: (r) => r.id },
  { key: 'status', header: 'Status', value: (r) => r.status },
  { key: 'suite', header: 'Suite', value: (r) => String(r.suite_id ?? '') },
  { key: 'adapter', header: 'Adapter', value: (r) => String(r.agent_adapter ?? '') },
  { key: 'reps', header: 'Reps', value: (r) => Number(r.repetitions ?? 0), numeric: true },
]

function useExperiments() {
  const [data, setData] = useState<ExperimentRow[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    if (!isServerMode()) {
      setData(DEMO_EXPERIMENTS)
      setLoading(false)
      return () => {
        alive = false
      }
    }
    listExperiments()
      .then((d) => alive && setData(d))
      .catch((e: unknown) => alive && setError(String(e)))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [])
  return { data, loading, error }
}

export function ExperimentsPage() {
  const [live, setLive] = useState<string[]>([])
  useEffect(() => {
    const off = subscribeEvents((e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data as string) as { type?: string; id?: string }
        if (d.type && d.id) setLive((prev) => [`${d.type}:${d.id}`, ...prev].slice(0, 20))
      } catch {
        /* ignore malformed frames */
      }
    })
    return off
  }, [])
  const state = useExperiments()
  return (
    <ServerGate>
      <section>
        <h1>Experiments</h1>
        <p><ServerStatus /></p>
        <p><Link className="btn" to="/workspace/experiments/new">New experiment →</Link></p>
        {isServerMode() && (
          <div className="card">
            <strong>Live progress (SSE)</strong>
            {live.length === 0 ? (
              <p className="muted">Waiting for events…</p>
            ) : (
              <ul className="timeline">{live.map((l, i) => <li key={i}>{l}</li>)}</ul>
            )}
          </div>
        )}
        {state.loading && <Loading />}
        {state.error && <ErrorState message={state.error} />}
        {state.data && <DataTable rows={state.data} columns={EXP_COLS} emptyHint="No experiments yet. Create one in the builder." />}
      </section>
    </ServerGate>
  )
}

export function ExperimentBuilderPage() {
  const [suiteId, setSuiteId] = useState('fileops-core')
  const [adapter, setAdapter] = useState('scripted')
  const [reps, setReps] = useState(3)
  const [seed, setSeed] = useState(42)
  const [result, setResult] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (): Promise<void> => {
    setResult(null)
    setErr(null)
    try {
      const res = await apiPost<{ id: string; status: string }>('/api/v1/experiments', {
        suite_id: suiteId,
        agent_adapter: adapter,
        repetitions: reps,
        seed,
      })
      setResult(`Queued ${res.id} (${res.status})`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <ServerGate>
      <section>
        <h1>Experiment builder</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">Manifests pin suite, adapter, sampling and seed so runs stay reproducible.</span>
        </p>
        <form onSubmit={(e) => { e.preventDefault(); void submit() }}>
          <label className="field">Suite ID <input value={suiteId} onChange={(e) => setSuiteId(e.target.value)} /></label>
          <label className="field">Agent adapter
            <select value={adapter} onChange={(e) => setAdapter(e.target.value)}>
              {['scripted', 'subprocess', 'openai_compat'].map((a) => <option key={a}>{a}</option>)}
            </select>
          </label>
          <label className="field">Repetitions{' '}
            <input type="number" min={1} max={100} value={reps} onChange={(e) => setReps(Number(e.target.value))} />
          </label>
          <label className="field">Seed <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} /></label>
          <button className="btn" type="submit">Queue experiment</button>
        </form>
        {err && <ErrorState message={err} />}
        {result && <p role="status">{result}</p>}
      </section>
    </ServerGate>
  )
}

// ---------- workers ----------

const WORKER_COLS: Column<DemoWorker>[] = [
  { key: 'id', header: 'Worker', value: (w) => w.id },
  { key: 'os', header: 'OS / arch', value: (w) => `${w.os}/${w.arch}` },
  { key: 'containers', header: 'Containers', value: (w) => w.containers },
  { key: 'browser', header: 'Browser', value: (w) => w.browser },
  { key: 'gpu', header: 'GPU', value: (w) => w.gpu },
  { key: 'status', header: 'Status', value: (w) => w.status },
  { key: 'util', header: 'Utilization', value: (w) => `${Math.round(w.utilization * 100)}%`, numeric: true },
]

export function WorkersPage() {
  return (
    <ServerGate>
      <section>
        <h1>Workers & capacity</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">Capability inventory reported at enrollment: OS, architecture, container runtime, browser, GPU.</span>
        </p>
        <DataTable rows={DEMO_WORKERS} columns={WORKER_COLS} emptyHint="No workers enrolled." />
        <div className="grid stats">
          {DEMO_WORKERS.filter((w) => w.status !== 'offline').map((w) => (
            <div key={w.id} className="card">
              <Ring value={w.utilization} label={`${w.id} utilization`} />
              <span>{w.id}</span>
            </div>
          ))}
        </div>
      </section>
    </ServerGate>
  )
}

// ---------- system health ----------

interface HealthSnapshot {
  healthz: boolean
  readyz: boolean
  metricsText: string
}

export function SystemHealthPage() {
  const [info, setInfo] = useState<HealthSnapshot | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    if (!isServerMode()) return
    fetchHealth().then(setInfo).catch((e: unknown) => setErr(String(e)))
  }, [])
  return (
    <ServerGate>
      <section>
        <h1>System health</h1>
        <p><ServerStatus /></p>
        {err && <ErrorState message={err} />}
        {!isServerMode() && <EmptyState hint="Connect to a server to view live health, readiness and Prometheus metrics." />}
        {info && (
          <>
            <p>
              <span className={`badge ${info.healthz ? 'badge-ok' : 'badge-bad'}`}>healthz: {info.healthz ? 'ok' : 'down'}</span>{' '}
              <span className={`badge ${info.readyz ? 'badge-ok' : 'badge-bad'}`}>readyz: {info.readyz ? 'ready' : 'not ready'}</span>
            </p>
            <h2>Prometheus metrics</h2>
            <pre aria-label="Prometheus metrics">{info.metricsText || '(no metrics)'}</pre>
          </>
        )}
        {!info && isServerMode() && !err && <Loading label="Checking server…" />}
        <NoPermission hint="Pages show this automatically when the server answers HTTP 403 for a gated action." />
      </section>
    </ServerGate>
  )
}
