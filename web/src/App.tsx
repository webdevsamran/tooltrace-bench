import { useEffect, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import {
  AboutPage, ContributorsPage, DocsPage, HomePage, MethodologyPage,
} from './pages/overview'
import {
  AgentsPage, LeaderboardPage, ModelsPage, TaskDetailPage, TaskPacksPage,
} from './pages/browse'
import {
  ComparePage, FailureAnalysisPage, ReliabilityTrendsPage, ResultDetailPage,
} from './pages/results'

const NAV = [
  ['/', 'Home'],
  ['/leaderboard', 'Leaderboard'],
  ['/agents', 'Agents'],
  ['/models', 'Models'],
  ['/tasks', 'Task Packs'],
  ['/compare', 'Compare'],
  ['/trends', 'Reliability Trends'],
  ['/failures', 'Failure Analysis'],
  ['/methodology', 'Methodology'],
  ['/docs', 'Docs'],
  ['/contributors', 'Contributors'],
  ['/about', 'About'],
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
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('ttb-theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <div className="app">
      <a href="#main" className="skip-link">Skip to content</a>
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
      <main id="main" className="content">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/leaderboard" element={<LeaderboardPage />} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/models" element={<ModelsPage />} />
          <Route path="/tasks" element={<TaskPacksPage />} />
          <Route path="/tasks/:taskId" element={<TaskDetailPage />} />
          <Route path="/results/:bundle" element={<ResultDetailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/trends" element={<ReliabilityTrendsPage />} />
          <Route path="/failures" element={<FailureAnalysisPage />} />
          <Route path="/methodology" element={<MethodologyPage />} />
          <Route path="/docs" element={<DocsPage />} />
          <Route path="/contributors" element={<ContributorsPage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="*" element={<p className="state empty">Page not found.</p>} />
        </Routes>
      </main>
      <footer className="footer">
        <span>Apache-2.0 · Created by @webdevsamran · Data: validated repository bundles only</span>
      </footer>
    </div>
  )
}