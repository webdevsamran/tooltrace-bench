// Publication review queue for privileged operations.

import { isServerMode, type ApprovalRow } from '../../api'
import { DataTable, DemoBadge, type Column } from '../../components'
import { DEMO_APPROVALS } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

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
          <ServerStatus /> <span className="muted">
            Privileged actions — publishing results, enabling networked tasks, changing shared baselines,
            costly runs — require reviewer/admin approval before execution.
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={DEMO_APPROVALS} columns={APPROVAL_COLS} emptyHint="No approval requests pending." />
      </section>
    </ServerGate>
  )
}
