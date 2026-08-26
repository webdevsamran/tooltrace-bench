import { Suspense, lazy, useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { ErrorBoundary, Loading, OfflineBanner, useOnlineStatus } from './components'

// Route-level code splitting keeps the initial bundle small; each page chunk
// loads on first visit. Public dataset pages and the team console share the
// same component model in both static and self-hosted API modes.
import type { ComponentType } from 'react'
function page<T>(loader: () => Promise<T>, pick: (m: T) => ComponentType) {
  return lazy(async () => ({ default: pick(await loader()) }))
}

const HomePage = page(() => import('./pages/overview'), (m) => m.HomePage)
const MethodologyPage = page(() => import('./pages/overview'), (m) => m.MethodologyPage)
const DocsPage = page(() => import('./pages/overview'), (m) => m.DocsPage)
const ContributorsPage = page(() => import('./pages/overview'), (m) => m.ContributorsPage)
const AboutPage = page(() => import('./pages/overview'), (m) => m.AboutPage)
const LeaderboardPage = page(() => import('./pages/browse'), (m) => m.LeaderboardPage)
const AgentsPage = page(() => import('./pages/browse'), (m) => m.AgentsPage)
const ModelsPage = page(() => import('./pages/browse'), (m) => m.ModelsPage)
const TaskPacksPage = page(() => import('./pages/browse'), (m) => m.TaskPacksPage)
const TaskDetailPage = page(() => import('./pages/browse'), (m) => m.TaskDetailPage)
const ResultDetailPage = page(() => import('./pages/results'), (m) => m.ResultDetailPage)
const ComparePage = page(() => import('./pages/results'), (m) => m.ComparePage)
const ReliabilityTrendsPage = page(() => import('./pages/results'), (m) => m.ReliabilityTrendsPage)
const FailureAnalysisPage = page(() => import('./pages/results'), (m) => m.FailureAnalysisPage)
const TraceExplorerPage = page(() => import('./pages/operations'), (m) => m.TraceExplorerPage)
const RecoveryAnalysisPage = page(() => import('./pages/operations'), (m) => m.RecoveryAnalysisPage)
const CostEfficiencyPage = page(() => import('./pages/operations'), (m) => m.CostEfficiencyPage)
const DatasetBrowserPage = page(() => import('./pages/operations'), (m) => m.DatasetBrowserPage)
const PluginCatalogPage = page(() => import('./pages/operations'), (m) => m.PluginCatalogPage)
const WorkspaceDashboardPage = page(() => import('./pages/workspace'), (m) => m.WorkspaceDashboardPage)
const ExperimentsPage = page(() => import('./pages/workspace'), (m) => m.ExperimentsPage)
const ExperimentBuilderPage = page(() => import('./pages/workspace'), (m) => m.ExperimentBuilderPage)
const WorkersPage = page(() => import('./pages/workspace'), (m) => m.WorkersPage)
const SystemHealthPage = page(() => import('./pages/workspace'), (m) => m.SystemHealthPage)
const BaselinesPage = page(() => import('./pages/workspace2'), (m) => m.BaselinesPage)
const TaskStudioPage = page(() => import('./pages/workspace2'), (m) => m.TaskStudioPage)
const ReviewQueuePage = page(() => import('./pages/workspace2'), (m) => m.ReviewQueuePage)
const UsersPage = page(() => import('./pages/workspace2'), (m) => m.UsersPage)
const PoliciesBudgetsPage = page(() => import('./pages/workspace3'), (m) => m.PoliciesBudgetsPage)
const AuditLogPage = page(() => import('./pages/workspace3'), (m) => m.AuditLogPage)
const WebhooksPage = page(() => import('./pages/workspace3'), (m) => m.WebhooksPage)
const RetentionSettingsPage = page(() => import('./pages/workspace3'), (m) => m.RetentionSettingsPage)


function NotFound() {
  return <p className="state empty">Page not found.</p>
}

const NAV = [
  ['/', 'Home'],
  ['/leaderboard', 'Leaderboard'],
  ['/agents', 'Agents'],
  ['/models', 'Models'],
  ['/tasks', 'Task Packs'],
  ['/compare', 'Compare'],
  ['/trends', 'Trends'],
  ['/failures', 'Failures'],
  ['/traces', 'Traces'],
  ['/recovery', 'Recovery'],
  ['/efficiency', 'Efficiency'],
  ['/dataset', 'Dataset'],
  ['/plugins', 'Plugins'],
] as const

const NAV_MORE = [
  ['/methodology', 'Methodology'],
  ['/docs', 'Docs'],
  ['/contributors', 'Contributors'],
  ['/about', 'About'],
] as const

const NAV_WORKSPACE = [
  ['/workspace', 'Dashboard'],
  ['/workspace/experiments', 'Experiments'],
  ['/workspace/experiments/new', 'Builder'],
  ['/workspace/workers', 'Workers'],
  ['/workspace/baselines', 'Baselines'],
  ['/workspace/studio', 'Studio'],
  ['/workspace/reviews', 'Reviews'],
  ['/workspace/users', 'Users'],
  ['/workspace/policies', 'Policies'],
  ['/workspace/audit', 'Audit'],
  ['/workspace/webhooks', 'Webhooks'],
  ['/workspace/settings', 'Settings'],
  ['/workspace/health', 'Health'],
] as const

function GlobalSearch() {
  const [q, setQ] = useState('')
  const location = useLocation()
  // Shareable filters: the query is mirrored into the URL hash fragment.
  useEffect(() => {
    if (q) window.history.replaceState(null, '', `#q=${encodeURIComponent(q)}`)
    else if (window.location.hash.startsWith('#q=')) window.history.replaceState(null, '', window.location.pathname)
  }, [q])
  void location
  return (
    <input
      className="search"
      type="search"
      placeholder="Search tasks, agents, results… (filters tables on data pages)"
      value={q}
      aria-label="Global search"
      onChange={(e) => setQ(e.target.value)}
    />
  )
}

export default function App() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('ttb-theme')
    return saved ? saved === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches
  })
  const online = useOnlineStatus()
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('ttb-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <OfflineBanner online={online} />
      <header className="topbar">
        <NavLink to="/" className="brand">ToolTrace<span> Bench</span></NavLink>
        <nav aria-label="Primary">
          {NAV.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'active' : '')}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-actions">
          <GlobalSearch />
          <button type="button" className="theme-toggle" onClick={() => setDark(!dark)}
            aria-label={dark ? 'Switch to light mode' : 'Switch to dark mode'}>
            {dark ? '☀' : '☾'}
          </button>
        </div>
      </header>
      <nav className="subbar" aria-label="About and documentation">
        {NAV_MORE.map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => (isActive ? 'active' : '')}>{label}</NavLink>
        ))}
      </nav>
      <nav className="subbar workspace" aria-label="Workspace console">
        <span className="subbar-label">Workspace</span>
        {NAV_WORKSPACE.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === '/workspace'} className={({ isActive }) => (isActive ? 'active' : '')}>
            {label}
          </NavLink>
        ))}
      </nav>
      <main id="main" className="content">
        <ErrorBoundary>
          <Suspense fallback={<Loading />}>
            <Routes>
              {/* Public dataset & analysis console */}
              <Route path="/" element={<HomePage />} />
              <Route path="/methodology" element={<MethodologyPage />} />
              <Route path="/docs" element={<DocsPage />} />
              <Route path="/contributors" element={<ContributorsPage />} />
              <Route path="/about" element={<AboutPage />} />
              <Route path="/leaderboard" element={<LeaderboardPage />} />
              <Route path="/agents" element={<AgentsPage />} />
              <Route path="/models" element={<ModelsPage />} />
              <Route path="/tasks" element={<TaskPacksPage />} />
              <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
              <Route path="/results/:bundle" element={<ResultDetailPage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="/trends" element={<ReliabilityTrendsPage />} />
              <Route path="/failures" element={<FailureAnalysisPage />} />
              <Route path="/traces" element={<TraceExplorerPage />} />
              <Route path="/recovery" element={<RecoveryAnalysisPage />} />
              <Route path="/efficiency" element={<CostEfficiencyPage />} />
              <Route path="/dataset" element={<DatasetBrowserPage />} />
              <Route path="/plugins" element={<PluginCatalogPage />} />
              {/* Self-hosted team / operations console */}
              <Route path="/workspace" element={<WorkspaceDashboardPage />} />
              <Route path="/workspace/experiments" element={<ExperimentsPage />} />
              <Route path="/workspace/experiments/new" element={<ExperimentBuilderPage />} />
              <Route path="/workspace/workers" element={<WorkersPage />} />
              <Route path="/workspace/health" element={<SystemHealthPage />} />
              <Route path="/workspace/baselines" element={<BaselinesPage />} />
              <Route path="/workspace/studio" element={<TaskStudioPage />} />
              <Route path="/workspace/reviews" element={<ReviewQueuePage />} />
              <Route path="/workspace/users" element={<UsersPage />} />
              <Route path="/workspace/policies" element={<PoliciesBudgetsPage />} />
              <Route path="/workspace/audit" element={<AuditLogPage />} />
              <Route path="/workspace/webhooks" element={<WebhooksPage />} />
              <Route path="/workspace/settings" element={<RetentionSettingsPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </main>
      <footer className="footer">
        <span>Apache-2.0 · Created by @webdevsamran · Data: validated repository bundles only</span>
      </footer>
    </div>
  )
}