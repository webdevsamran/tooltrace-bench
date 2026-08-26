// Users, teams & service accounts (RBAC) view.

import { isServerMode } from '../../api'
import { DataTable, DemoBadge, type Column } from '../../components'
import { DEMO_USERS, type DemoUser } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

const USER_COLS: Column<DemoUser>[] = [
  { key: 'id', header: 'ID', value: (u) => u.user_id },
  { key: 'name', header: 'Name', value: (u) => u.display_name },
  { key: 'role', header: 'RBAC role', value: (u) => u.role },
  { key: 'kind', header: 'Kind', value: (u) => u.kind },
]

export function UsersPage() {
  return (
    <ServerGate>
      <section>
        <h1>Users, teams & service accounts</h1>
        <p>
          <ServerStatus /> <span className="muted">
            RBAC roles: viewer, runner, task_author, reviewer, admin, service_account. API tokens are stored
            hashed with rotation metadata and scoped permissions.
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={DEMO_USERS} columns={USER_COLS} emptyHint="No members yet." />
      </section>
    </ServerGate>
  )
}
