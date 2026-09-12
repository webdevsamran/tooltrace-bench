// Publication review queue for privileged operations.

import { listApprovals, type ApprovalRow } from '../../api'
import { type Column } from '../../components'
import { DEMO_APPROVALS } from '../demoData'
import { ConsoleData, ServerGate, ServerStatus } from './shared'

const APPROVAL_COLS: Column<ApprovalRow>[] = [
  { key: 'id', header: 'Request', value: (a) => a.request_id },
  { key: 'action', header: 'Action', value: (a) => a.action },
  { key: 'ws', header: 'Workspace', value: (a) => a.workspace_id },
  { key: 'state', header: 'State', value: (a) => a.state },
  { key: 'by', header: 'Requested by', value: (a) => String(a.requested_by ?? '') },
]

export function ReviewQueuePage() {
  return (
    <ServerGate>
      <section>
        <h1>Publication review queue</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            Privileged actions -- publishing results, enabling networked tasks, changing shared
            baselines, costly runs -- require reviewer or admin approval before execution.
          </span>
        </p>
        <ConsoleData
          load={listApprovals}
          demo={DEMO_APPROVALS}
          columns={APPROVAL_COLS}
          emptyHint="Nothing is waiting on a decision."
        />
      </section>
    </ServerGate>
  )
}
