// Policy-as-code and budget/quota management view.

import { isServerMode } from '../../api'
import { DataTable, DemoBadge, type Column } from '../../components'
import { ServerGate, ServerStatus } from './shared'

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
