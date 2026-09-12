// Named baselines used by the regression gate.

import { listBaselines, type BaselineRow } from '../../api'
import { type Column } from '../../components'
import { DEMO_BASELINES } from '../demoData'
import { ConsoleData, ServerGate, ServerStatus } from './shared'

const BASELINE_COLS: Column<BaselineRow>[] = [
  { key: 'name', header: 'Name', value: (b) => b.name },
  { key: 'bundle', header: 'Bundle', value: (b) => b.bundle },
]

export function BaselinesPage() {
  return (
    <ServerGate>
      <section>
        <h1>Baselines &amp; regressions</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            <code>tooltrace baseline --name N --bundle B</code> records one, and{' '}
            <code>tooltrace regression</code> gates a pull request against it. The registry is a
            file in the server's working directory, so this table is exactly what the CLI wrote --
            not a second copy that could disagree with it.
          </span>
        </p>
        <ConsoleData
          load={listBaselines}
          demo={DEMO_BASELINES}
          columns={BASELINE_COLS}
          emptyHint="No baselines recorded yet."
        />
      </section>
    </ServerGate>
  )
}
