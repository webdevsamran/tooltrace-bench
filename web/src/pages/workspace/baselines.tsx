// Baselines & regressions view for the self-hosted console.

import { isServerMode } from '../../api'
import { DataTable, DemoBadge, type Column } from '../../components'
import { DEMO_BASELINES, type DemoBaseline } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

const BASELINE_COLS: Column<DemoBaseline>[] = [
  { key: 'scope', header: 'Scope', value: (b) => b.scope },
  { key: 'metric', header: 'Metric', value: (b) => b.metric },
  { key: 'value', header: 'Baseline', value: (b) => (b.value > 10 ? String(b.value) : b.value.toFixed(3)), numeric: true },
  {
    key: 'tolerance',
    header: 'Tolerance ±',
    value: (b) => (b.tolerance > 10 ? String(b.tolerance) : b.tolerance.toFixed(3)),
    numeric: true,
  },
  { key: 'updated', header: 'Last updated', value: (b) => b.last_updated },
]

export function BaselinesPage() {
  return (
    <ServerGate>
      <section>
        <h1>Baselines & regressions</h1>
        <p>
          <ServerStatus /> <span className="muted">
            Suite-, domain-, task- and metric-level baselines with tolerances; CI gates exit non-zero on
            regression beyond tolerance (<code>tooltrace regression</code>).
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={DEMO_BASELINES} columns={BASELINE_COLS} emptyHint="No shared baselines yet." />
      </section>
    </ServerGate>
  )
}
