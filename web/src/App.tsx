import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { ErrorBoundary, Loading, OfflineBanner, useOnlineStatus } from './components'
import { CommandPalette, usePaletteHotkey, type Command } from './palette'
import { useViewTransition } from './motion'

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
const SecurityPosturePage = page(() => import('./pages/assurance'), (m) => m.SecurityPosturePage)
const EvidencePage = page(() => import('./pages/assurance'), (m) => m.EvidencePage)
const RecoveryAnalysisPage = page(() => import('./pages/operations'), (m) => m.RecoveryAnalysisPage)
const CostEfficiencyPage = page(() => import('./pages/operations'), (m) => m.CostEfficiencyPage)
const ParetoExplorerPage = page(() => import('./pages/operations'), (m) => m.ParetoExplorerPage)
const RunComparePage = page(() => import('./pages/results'), (m) => m.RunComparePage)
const DatasetBrowserPage = page(() => import('./pages/operations'), (m) => m.DatasetBrowserPage)
const PluginCatalogPage = page(() => import('./pages/operations'), (m) => m.PluginCatalogPage)
const WorkspaceDashboardPage = page(() => import('./pages/workspace/dashboard'), (m) => m.WorkspaceDashboardPage)
const LiveConsolePage = page(() => import('./pages/workspace/console'), (m) => m.LiveConsolePage)
const ExperimentsPage = page(() => import('./pages/workspace/experiments'), (m) => m.ExperimentsPage)
const ExperimentBuilderPage = page(() => import('./pages/workspace/experiments'), (m) => m.ExperimentBuilderPage)
const WorkersPage = page(() => import('./pages/workspace/workers'), (m) => m.WorkersPage)
const SystemHealthPage = page(() => import('./pages/workspace/workers'), (m) => m.SystemHealthPage)
const BaselinesPage = page(() => import('./pages/workspace/baselines'), (m) => m.BaselinesPage)
const TaskStudioPage = page(() => import('./pages/workspace/studio'), (m) => m.TaskStudioPage)
const ReviewQueuePage = page(() => import('./pages/workspace/review'), (m) => m.ReviewQueuePage)
const UsersPage = page(() => import('./pages/workspace/users'), (m) => m.UsersPage)
const PoliciesBudgetsPage = page(() => import('./pages/workspace/policies'), (m) => m.PoliciesBudgetsPage)
const AuditLogPage = page(() => import('./pages/workspace/audit'), (m) => m.AuditLogPage)
const WebhooksPage = page(() => import('./pages/workspace/webhooks'), (m) => m.WebhooksPage)
const RetentionSettingsPage = page(() => import('./pages/workspace/settings'), (m) => m.RetentionSettingsPage)

function NotFound() {
  return <p className="state empty">Page not found.</p>
}

/**
 * Navigation is grouped into four sections rather than three stacked bars.
 *
 * Every link used to be visible at once — thirteen in the top bar, four below
 * it, twelve more for the workspace — which is twenty-nine competing targets
 * before any page content. The top bar now carries the sections, the sidebar
 * carries the current section's pages, and Cmd-K reaches anything directly.
 */
export interface NavSection {
  id: string
  label: string
  home: string
  items: readonly (readonly [string, string])[]
}

export const NAV_SECTIONS: readonly NavSection[] = [
  {
    id: 'explore',
    label: 'Explore',
    home: '/leaderboard',
    items: [
      ['/leaderboard', 'Leaderboard'],
      ['/agents', 'Agents'],
      ['/models', 'Models'],
      ['/tasks', 'Task Packs'],
      ['/dataset', 'Dataset'],
      ['/plugins', 'Plugins'],
    ],
  },
  {
    id: 'analyze',
    label: 'Analyze',
    home: '/compare',
    items: [
      ['/compare', 'Compare'],
      ['/compare/runs', 'Run diff'],
      ['/trends', 'Trends'],
      ['/failures', 'Failures'],
      ['/recovery', 'Recovery'],
      ['/efficiency', 'Efficiency'],
      ['/frontier', 'Frontier'],
      ['/traces', 'Traces'],
      ['/security', 'Security'],
      ['/evidence', 'Evidence'],
    ],
  },
  {
    id: 'workspace',
    label: 'Workspace',
    home: '/workspace',
    items: [
      ['/workspace', 'Dashboard'],
      ['/workspace/console', 'Live console'],
      ['/workspace/experiments', 'Experiments'],
      ['/workspace/experiments/new', 'Builder'],
      ['/workspace/workers', 'Workers'],
      ['/workspace/health', 'Health'],
      ['/workspace/baselines', 'Baselines'],
      ['/workspace/studio', 'Studio'],
      ['/workspace/reviews', 'Reviews'],
      ['/workspace/users', 'Users'],
      ['/workspace/policies', 'Policies'],
      ['/workspace/audit', 'Audit'],
      ['/workspace/webhooks', 'Webhooks'],
      ['/workspace/settings', 'Settings'],
    ],
  },
  {
    id: 'about',
    label: 'About',
    home: '/methodology',
    items: [
      ['/methodology', 'Methodology'],
      ['/docs', 'Docs'],
      ['/contributors', 'Contributors'],
      ['/about', 'About'],
    ],
  },
] as const

/** The section owning a path, by longest matching item prefix. */
export function sectionFor(pathname: string): NavSection | null {
  let best: NavSection | null = null
  let bestLength = 0
  for (const section of NAV_SECTIONS) {
    for (const [path] of section.items) {
      const matches = pathname === path || pathname.startsWith(`${path}/`)
      if (matches && path.length > bestLength) {
        best = section
        bestLength = path.length
      }
    }
  }
  // Detail routes hang off their list page.
  if (!best && pathname.startsWith('/tasks')) return NAV_SECTIONS[0]
  if (!best && pathname.startsWith('/results')) return NAV_SECTIONS[1]
  return best
}

type ThemeChoice = 'light' | 'dark' | 'system'

const THEME_LABEL: Record<ThemeChoice, string> = {
  light: 'Light',
  dark: 'Dark',
  system: 'System',
}
const THEME_GLYPH: Record<ThemeChoice, string> = { light: '☀', dark: '☾', system: '◐' }

function useTheme(): [ThemeChoice, () => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => {
    const saved = localStorage.getItem('ttb-theme')
    return saved === 'light' || saved === 'dark' || saved === 'system' ? saved : 'system'
  })

  useEffect(() => {
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const apply = () => {
      const dark = choice === 'dark' || (choice === 'system' && media.matches)
      document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    }
    apply()
    localStorage.setItem('ttb-theme', choice)
    // Following the OS while set to "system" is the whole point of the option.
    if (choice !== 'system') return undefined
    media.addEventListener('change', apply)
    return () => media.removeEventListener('change', apply)
  }, [choice])

  const cycle = useCallback(
    () => setChoice((c) => (c === 'system' ? 'light' : c === 'light' ? 'dark' : 'system')),
    [],
  )
  return [choice, cycle]
}

export default function App() {
  const [theme, cycleTheme] = useTheme()
  // The location the routes render. One transition behind the router while a
  // cross-fade is running, and identical to it everywhere else -- including
  // Firefox, and anyone who asked for reduced motion. See `motion.tsx`.
  const rendered = useViewTransition()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const online = useOnlineStatus()
  const location = useLocation()
  const section = sectionFor(location.pathname)

  const openPalette = useCallback(() => setPaletteOpen(true), [])
  usePaletteHotkey(openPalette)

  const commands = useMemo<Command[]>(() => {
    const routes: Command[] = NAV_SECTIONS.flatMap((s) =>
      s.items.map(([to, label]) => ({ id: to, label, group: s.label, to })),
    )
    return [
      { id: '/', label: 'Home', group: 'Overview', to: '/' },
      ...routes,
      {
        id: 'theme',
        label: `Theme: ${THEME_LABEL[theme]} — switch`,
        group: 'Appearance',
        keywords: 'dark light system colour color',
        run: cycleTheme,
      },
    ]
  }, [theme, cycleTheme])

  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
      <OfflineBanner online={online} />

      <header className="topbar">
        <NavLink to="/" className="brand">ToolTrace<span>Bench</span></NavLink>
        <nav aria-label="Primary">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Home
          </NavLink>
          {NAV_SECTIONS.map((s) => (
            <NavLink
              key={s.id}
              to={s.home}
              className={section?.id === s.id ? 'active' : ''}
              aria-current={section?.id === s.id ? 'page' : undefined}
            >
              {s.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar-actions">
          <button type="button" className="search" onClick={openPalette}>
            <span aria-hidden="true">⌕</span>
            <span className="search-text">Search pages…</span>
            <kbd>⌘K</kbd>
          </button>
          <button
            type="button"
            className="theme-toggle"
            onClick={cycleTheme}
            aria-label={`Theme: ${THEME_LABEL[theme]}. Activate to change.`}
          >
            <span aria-hidden="true">{THEME_GLYPH[theme]}</span>
          </button>
        </div>
      </header>

      <div className="shell">
        {section && (
          <nav className="sidebar" aria-label={`${section.label} section`}>
            <div className="sidebar-group">
              {/* Deliberately not a heading: the <nav> already carries an
                  accessible name, and a heading here would inject a duplicate
                  "Workspace"/"Explore" into every page's document outline. */}
              <p className="sidebar-label">{section.label}</p>
              <ul>
                {section.items.map(([to, label]) => (
                  <li key={to}>
                    <NavLink
                      to={to}
                      end={to === '/workspace' || to === '/tasks'}
                      className={({ isActive }) => (isActive ? 'active' : '')}
                    >
                      {label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </div>
          </nav>
        )}

        <main id="main" className="content">
          <ErrorBoundary>
            <Suspense fallback={<Loading />}>
              <Routes location={rendered}>
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
                <Route path="/compare/runs" element={<RunComparePage />} />
                <Route path="/trends" element={<ReliabilityTrendsPage />} />
                <Route path="/failures" element={<FailureAnalysisPage />} />
                <Route path="/traces" element={<TraceExplorerPage />} />
                <Route path="/security" element={<SecurityPosturePage />} />
                <Route path="/evidence" element={<EvidencePage />} />
                <Route path="/recovery" element={<RecoveryAnalysisPage />} />
                <Route path="/efficiency" element={<CostEfficiencyPage />} />
                <Route path="/frontier" element={<ParetoExplorerPage />} />
                <Route path="/dataset" element={<DatasetBrowserPage />} />
                <Route path="/plugins" element={<PluginCatalogPage />} />
                {/* Self-hosted team / operations console */}
                <Route path="/workspace" element={<WorkspaceDashboardPage />} />
                <Route path="/workspace/console" element={<LiveConsolePage />} />
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
      </div>

      <footer className="footer">
        <span>Apache-2.0 · Created by @webdevsamran · Data: validated repository bundles only</span>
      </footer>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={commands}
      />
    </div>
  )
}
