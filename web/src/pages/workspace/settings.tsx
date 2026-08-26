// Retention, backup/export and connection settings.

import { isServerMode } from '../../api'
import { DemoBadge } from '../../components'
import { ServerGate, ServerStatus } from './shared'

export function RetentionSettingsPage() {
  return (
    <ServerGate>
      <section>
        <h1>Retention & settings</h1>
        <p><ServerStatus /></p>
        {!isServerMode() && <DemoBadge />}
        <div className="card">
          <strong>Artifact retention</strong>
          <p className="muted">
            Configurable retention with deletion of expired records and legal-hold-style exemptions.
            Deletion is administrative only — it is not a legal-compliance claim.
          </p>
        </div>
        <div className="card">
          <strong>Backup / export</strong>
          <p className="muted">
            Self-hosted metadata and artifact references support backup/restore and export/import; see{' '}
            <code>docs/self-hosting.md#backup-and-restore</code>.
          </p>
        </div>
        <div className="card">
          <strong>Connection</strong>
          <p className="muted">
            Server URL and token are stored only in this browser. The token is sent solely as a Bearer
            header to your own server — never logged or embedded in shared URLs.
          </p>
        </div>
      </section>
    </ServerGate>
  )
}
