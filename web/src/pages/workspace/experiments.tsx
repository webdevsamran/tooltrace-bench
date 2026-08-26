// Experiments list + builder with live SSE progress monitoring.

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiPost, isServerMode, listExperiments, subscribeEvents, type ExperimentRow } from '../../api'
import { DataTable, ErrorState, Loading, type Column } from '../../components'
import { DEMO_EXPERIMENTS } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

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
