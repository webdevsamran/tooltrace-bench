// Worker capacity inventory and live system health/readiness views.

import { useEffect, useState } from 'react'
import { fetchHealth, isServerMode } from '../../api'
import { DataTable, EmptyState, ErrorState, Loading, NoPermission, type Column } from '../../components'
import { Ring } from '../../charts'
import { DEMO_WORKERS, type DemoWorker } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

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
