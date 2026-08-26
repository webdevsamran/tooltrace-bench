// Workspace dashboard: entry card grid linking every console section.

import { Link } from 'react-router-dom'
import { ServerStatus } from './shared'

const WORKSPACE_SECTIONS = [
  ['Experiments', '/workspace/experiments'],
  ['Experiment builder', '/workspace/experiments/new'],
  ['Workers & capacity', '/workspace/workers'],
  ['Baselines & regressions', '/workspace/baselines'],
  ['Task Authoring Studio', '/workspace/studio'],
  ['Publication queue', '/workspace/reviews'],
  ['Users & service accounts', '/workspace/users'],
  ['Policies & budgets', '/workspace/policies'],
  ['Audit log', '/workspace/audit'],
  ['Webhooks', '/workspace/webhooks'],
  ['Retention & settings', '/workspace/settings'],
  ['System health', '/workspace/health'],
] as const

export function WorkspaceDashboardPage() {
  return (
    <section>
      <h1>Workspace</h1>
      <p><ServerStatus /> <span className="muted">Team collaboration on your own infrastructure.</span></p>
      <nav aria-label="Workspace sections" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '.6rem' }}>
        {WORKSPACE_SECTIONS.map(([label, to]) => (
          <Link key={to} className="card" to={to} style={{ textDecoration: 'none', color: 'inherit' }}>
            <strong style={{ fontSize: '.95rem' }}>{label}</strong>
          </Link>
        ))}
      </nav>
    </section>
  )
}
