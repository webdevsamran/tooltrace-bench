// Policy-as-code and budget/quota management view.

import { getPolicies, isServerMode, useAsync, type PolicyView } from '../../api'
import { DataTable, DemoBadge, ErrorState, Loading, type Column } from '../../components'
import { ServerGate, ServerStatus } from './shared'

interface PolicyRow {
  setting: string
  value: string
}

const POLICY_COLS: Column<PolicyRow>[] = [
  { key: 'setting', header: 'Policy', value: (p) => p.setting },
  { key: 'value', header: 'Value', value: (p) => p.value },
]

/**
 * Rows built from the policy the server returns, not from a list of settings
 * somebody hoped it had.
 *
 * The previous fixture advertised `max_concurrency`, `monthly_token_budget` and
 * `monetary_budget_usd`. `WorkspacePolicy` has none of them, and no code in this
 * project enforces any of them, so an operator comparing tools was reading a
 * wish list formatted as a configuration table. Deriving the rows from the
 * payload means the table can only show settings that exist.
 */
function toRows(view: PolicyView | null): PolicyRow[] {
  if (!view?.policy) return []
  return Object.entries(view.policy).map(([setting, value]) => ({
    setting,
    value: Array.isArray(value) ? value.join(', ') : String(value),
  }))
}

const DEMO_POLICY: PolicyView = {
  workspace_id: 'ws-demo',
  policy: {
    allowed_providers: ['openai_compat', 'scripted'],
    allowed_models: ['*'],
    allowed_tools: ['read_file', 'write_file', 'patch_file', 'shell'],
    allowed_task_packs: ['*'],
    network_modes: ['offline'],
    max_runs_per_day: 500,
    publication_requires_approval: true,
  },
  quota: { limits: { runs: 500 }, used: { runs: 128 } },
}

export function PoliciesBudgetsPage() {
  const live = isServerMode()
  const state = useAsync<PolicyView>(
    () => (live ? getPolicies() : Promise.resolve(DEMO_POLICY)),
    [live],
  )

  return (
    <ServerGate>
      <section>
        <h1>Policies &amp; budgets</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            Policy-as-code governs which providers, models, tools and task packs a workspace may
            use, whether a task may reach the network, and whether publishing needs a reviewer.
            Quotas are counted per workspace and answer <code>429</code> when exhausted.
          </span>
        </p>
        {!live && <DemoBadge />}
        {state.loading && <Loading />}
        {state.error && <ErrorState message={state.error} />}
        {state.data && (
          <>
            <p className="muted">
              Workspace <code>{state.data.workspace_id}</code>
            </p>
            <DataTable
              rows={toRows(state.data)}
              columns={POLICY_COLS}
              emptyHint="No policy is configured for this workspace, so the server's defaults apply."
            />
            {state.data.quota ? (
              <div className="grid stats">
                {Object.entries(state.data.quota.limits).map(([resource, limit]) => (
                  <div key={resource} className="stat">
                    <span className="stat-label">{resource}</span>
                    <span className="stat-value">
                      {state.data?.quota?.used[resource] ?? 0} / {limit}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                No quota is configured for this workspace. That is not "unlimited" in any enforced
                sense — it means nothing is counting.
              </p>
            )}
          </>
        )}
      </section>
    </ServerGate>
  )
}
