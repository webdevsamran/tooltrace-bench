// Immutable hash-chained audit log view.

import { isServerMode } from '../../api'
import { DataTable, DemoBadge, type Column } from '../../components'
import { DEMO_AUDIT } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

interface AuditDisplay {
  seq: number
  actor: string
  action: string
  target: string
  at: string
  hash?: string
}

const AUDIT_COLS: Column<AuditDisplay>[] = [
  { key: 'seq', header: '#', value: (a) => a.seq, numeric: true },
  { key: 'at', header: 'When (UTC)', value: (a) => a.at },
  { key: 'actor', header: 'Actor', value: (a) => a.actor },
  { key: 'action', header: 'Action', value: (a) => a.action },
  { key: 'target', header: 'Target', value: (a) => a.target },
  { key: 'hash', header: 'Chain hash', value: (a) => String(a.hash ?? '') },
]

export function AuditLogPage() {
  const rows: AuditDisplay[] = DEMO_AUDIT.map((a) => ({
    seq: a.seq, actor: a.actor, action: a.action, target: a.target, at: a.at, hash: a.hash,
  }))
  return (
    <ServerGate>
      <section>
        <h1>Audit log</h1>
        <p>
          <ServerStatus /> <span className="muted">
            Immutable hash-chained events for privileged actions and publication decisions. Each entry
            commits to its predecessor; tampering breaks verification.
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={rows} columns={AUDIT_COLS} emptyHint="No audit events." />
      </section>
    </ServerGate>
  )
}
