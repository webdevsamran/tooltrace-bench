// Worker capacity inventory and live system health/readiness views.

import { useEffect, useState } from 'react'
import { fetchHealth, listWorkers, type WorkerRow } from '../../api'
import { EmptyState, ErrorState, Loading, NoPermission, type Column } from '../../components'
import { DEMO_WORKERS } from '../demoData'
import { ConsoleData, ServerGate, ServerStatus } from './shared'

/**
 * The columns are what a `WorkerInventory` actually reports.
 *
 * They were `status` and a `utilization` percentage rendered as a progress
 * ring. Nothing in this project measures either: there is no heartbeat, so
 * "idle/busy/offline" was a guess, and the ring drew a number that came from a
 * fixture. Both are gone rather than reworded -- a dashboard that shows a
 * plausible number nobody computed is the failure this whole project is built
 * against.
 *
 * `gpu_detection` is here because `gpu` alone is not an answer: an AMD or Apple
 * GPU on a machine without `nvidia-smi` is indistinguishable from no GPU, and
 * the field says which of the two this is.
 */
const WORKER_COLS: Column<WorkerRow>[] = [
  { key: 'id', header: 'Worker', value: (w) => w.worker_id },
  { key: 'os', header: 'OS / arch', value: (w) => `${w.os_name} / ${w.arch}` },
  { key: 'python', header: 'Python', value: (w) => w.python_version },
  { key: 'containers', header: 'Containers', value: (w) => w.container_runtime ?? 'none' },
  {
    key: 'gpu',
    header: 'GPU',
    value: (w) => (w.gpu ? w.gpu_names.join(', ') || 'yes' : `none (${w.gpu_detection})`),
  },
  { key: 'conc', header: 'Max concurrency', value: (w) => w.max_concurrency, numeric: true },
]

export function WorkersPage() {
  return (
    <ServerGate>
      <section>
        <h1>Workers &amp; capacity</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            Capability inventory measured on the node, not declared: OS, architecture, Python,
            container runtime and GPU. A server reports one worker — itself. Fleet workers enrol
            through a shared queue with <code>tooltrace fleet work</code> and are not registered
            with this process, so they are not listed here rather than being guessed at.
          </span>
        </p>
        <ConsoleData
          load={listWorkers}
          demo={DEMO_WORKERS}
          columns={WORKER_COLS}
          emptyHint="No workers reported."
        />
      </section>
    </ServerGate>
  )
}

export function SystemHealthPage() {
  const [health, setHealth] = useState<Awaited<ReturnType<typeof fetchHealth>> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    fetchHealth()
      .then((h) => {
        if (alive) setHealth(h)
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <ServerGate>
      <section>
        <h1>System health</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            <code>/healthz</code> answers whether the process is up; <code>/readyz</code> whether it
            is willing to take work. They are separate questions and a single green dot would
            conflate them.
          </span>
        </p>
        {error && <ErrorState message={error} />}
        {!health && !error && <Loading />}
        {health && (
          <div className="grid stats">
            <div className="stat">
              <span className="stat-label">Live (/healthz)</span>
              <span className="stat-value">{health.healthz ? 'yes' : 'no'}</span>
            </div>
            <div className="stat">
              <span className="stat-label">Ready (/readyz)</span>
              <span className="stat-value">{health.readyz ? 'yes' : 'no'}</span>
            </div>
          </div>
        )}
      </section>
    </ServerGate>
  )
}

export { EmptyState, NoPermission }
