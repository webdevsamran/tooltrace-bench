// Self-hosted team/enterprise console (part 3): policies & budgets,
// immutable audit log, webhooks/integrations, retention & settings.

import { isServerMode } from '../api'
import { DataTable, DemoBadge, type Column } from '../components'
import { ServerGate, ServerStatus } from './workspace'
import { DEMO_AUDIT, DEMO_WEBHOOKS } from './demoData'

// ---------- policies & budgets ----------

export interface PolicyRow {
  scope: string
  setting: string
  value: string
}

const POLICY_DEMO: PolicyRow[] = [
  { scope: 'ws-demo', setting: 'allowed_providers', value: 'openai_compat(local), scripted' },
  { scope: 'ws-demo', setting: 'network_modes', value: 'offline, local-fixtures-only' },
  { scope: 'ws-demo', setting: 'max_runs_per_day', value: '500' },
  { scope: 'ws-demo', setting: 'max_concurrency', value: '8' },
  { scope: 'ws-demo', setting: 'monthly_token_budget', value: '20,000,000' },
  { scope: 'ws-demo', setting: 'monetary_budget_usd', value: '150.00' },
]

const POLICY_COLS: Column<PolicyRow>[] = [
  { key: 'scope', header: 'Workspace', value: (p) => p.scope },
  { key: 'setting', header: 'Policy', value: (p) => p.setting },
  { key: 'value', header: 'Value', value: (p) => p.value },
]

export function PoliciesBudgetsPage() {
  return (
    <ServerGate>
      <section>
        <h1>Policies & budgets</h1>
        <p>
          <ServerStatus /> <span className="muted">
            Policy-as-code governs allowed providers, models, tools, task packs, network modes and
            publication. Quotas enforce runs, concurrency, tokens and configured monetary budgets per
            workspace (HTTP 429 when exceeded).
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={POLICY_DEMO} columns={POLICY_COLS} emptyHint="No policies defined." />
      </section>
    </ServerGate>
  )
}

// ---------- audit log ----------

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

// ---------- webhooks ----------

interface WebhookDisplay {
  id: string
  url: string
  events: string
  status: string
}

const WEBHOOK_COLS: Column<WebhookDisplay>[] = [
  { key: 'id', header: 'ID', value: (w) => w.id },
  { key: 'url', header: 'Endpoint', value: (w) => w.url },
  { key: 'events', header: 'Events', value: (w) => w.events },
  { key: 'status', header: 'Delivery status', value: (w) => w.status },
]

export function WebhooksPage() {
  return (
    <ServerGate>
      <section>
        <h1>Webhooks & integrations</h1>
        <p>
          <ServerStatus /> <span className="muted">
            Deliveries are HMAC-SHA256 signed with retries and backoff. Email/Slack-compatible targets are
            generic webhook receivers — vendor secrets never enter core benchmark data.
          </span>
        </p>
        {!isServerMode() && <DemoBadge />}
        <DataTable rows={DEMO_WEBHOOKS} columns={WEBHOOK_COLS} emptyHint="No webhooks registered." />
      </section>
    </ServerGate>
  )
}

// ---------- retention & settings ----------

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
