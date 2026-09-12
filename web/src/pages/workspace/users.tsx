// Users, teams & service accounts (RBAC) view.

import { listUsers, type ConsoleUser } from '../../api'
import { type Column } from '../../components'
import { DEMO_USERS } from '../demoData'
import { ConsoleData, ServerGate, ServerStatus } from './shared'

const USER_COLS: Column<ConsoleUser>[] = [
  { key: 'id', header: 'ID', value: (u) => u.user_id },
  { key: 'name', header: 'Name', value: (u) => u.display_name },
  { key: 'role', header: 'RBAC role', value: (u) => u.role },
  { key: 'kind', header: 'Kind', value: (u) => u.kind },
]

export function UsersPage() {
  return (
    <ServerGate>
      <section>
        <h1>Users, teams &amp; service accounts</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            RBAC roles: viewer, auditor, runner, task_author, reviewer, admin, service_account. API
            tokens are stored hashed with rotation metadata and scoped permissions, and the members
            below are the ones in <em>your</em> workspace -- the server scopes the list rather than
            the console filtering it.
          </span>
        </p>
        <ConsoleData
          load={listUsers}
          demo={DEMO_USERS}
          columns={USER_COLS}
          emptyHint="No members yet. `tooltrace server` starts with an empty directory; enrol one through your auth provider."
        />
      </section>
    </ServerGate>
  )
}
