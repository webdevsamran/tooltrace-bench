import { useMemo, useState } from 'react'
import type { ReactNode } from 'react'

// ---------- states ----------

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" /> {label}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="state error" role="alert">
      <strong>Something went wrong.</strong> {message}
    </div>
  )
}

export function EmptyState({ hint }: { hint: string }) {
  return (
    <div className="state empty">
      <strong>No data yet.</strong> {hint}
    </div>
  )
}

// ---------- badges ----------

export function Badge({ kind, children }: { kind: 'ok' | 'bad' | 'warn' | 'info'; children: ReactNode }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}

export function SuccessBadge({ ok, partial }: { ok: boolean; partial?: boolean }) {
  if (ok) return <Badge kind="ok">PASS</Badge>
  if (partial) return <Badge kind="warn">PARTIAL</Badge>
  return <Badge kind="bad">FAIL</Badge>
}

// ---------- sortable + paginated table ----------

export interface Column<T> {
  key: string
  header: string
  value: (row: T) => string | number
  render?: (row: T) => ReactNode
  numeric?: boolean
}

export function DataTable<T>({
  rows,
  columns,
  pageSize = 15,
  emptyHint,
}: {
  rows: T[]
  columns: Column<T>[]
  pageSize?: number
  emptyHint: string
}) {
  const [sortKey, setSortKey] = useState(columns[0]?.key ?? '')
  const [asc, setAsc] = useState(true)
  const [page, setPage] = useState(0)

  const sorted = useMemo(() => {
    const col = columns.find((c) => c.key === sortKey)
    if (!col) return rows
    const copy = [...rows]
    copy.sort((a, b) => {
      const va = col.value(a)
      const vb = col.value(b)
      if (typeof va === 'number' && typeof vb === 'number') return asc ? va - vb : vb - va
      return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va))
    })
    return copy
  }, [rows, columns, sortKey, asc])

  const pages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const current = sorted.slice(page * pageSize, (page + 1) * pageSize)

  if (rows.length === 0) return <EmptyState hint={emptyHint} />

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                onClick={() => {
                  if (c.key === sortKey) setAsc(!asc)
                  else {
                    setSortKey(c.key)
                    setAsc(true)
                  }
                }}
                className={c.numeric ? 'num' : ''}
                aria-sort={c.key === sortKey ? (asc ? 'ascending' : 'descending') : 'none'}
              >
                <button type="button" className="th-btn">
                  {c.header} {c.key === sortKey ? (asc ? '▲' : '▼') : ''}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {current.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.numeric ? 'num' : ''}>
                  {c.render ? c.render(row) : String(c.value(row))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="pager">
        <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
          ← Prev
        </button>
        <span>
          Page {page + 1} / {pages} · {sorted.length} rows
        </span>
        <button type="button" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>
          Next →
        </button>
      </div>
    </div>
  )
}

// ---------- SVG charts (no chart dependency) ----------

export function BarChart({
  data,
  max,
  format,
}: {
  data: { label: string; value: number }[]
  max?: number
  format?: (v: number) => string
}) {
  if (data.length === 0) return <EmptyState hint="No chart data." />
  const top = max ?? Math.max(...data.map((d) => d.value), 1e-9)
  return (
    <div className="barchart" role="img" aria-label="bar chart">
      {data.map((d) => (
        <div key={d.label} className="bar-row">
          <span className="bar-label">{d.label}</span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${Math.min(100, (d.value / top) * 100)}%` }} />
          </span>
          <span className="bar-value">{format ? format(d.value) : d.value.toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

export function LineChart({
  series,
  width = 560,
  height = 180,
}: {
  series: { label: string; points: number[] }[]
  width?: number
  height?: number
}) {
  const all = series.flatMap((s) => s.points)
  if (all.length === 0) return <EmptyState hint="No trend data." />
  const lo = Math.min(...all)
  const hi = Math.max(...all)
  const span = hi - lo || 1
  const n = Math.max(...series.map((s) => s.points.length))
  const colors = ['#38bdf8', '#f472b6', '#4ade80', '#facc15']
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="linechart" role="img" aria-label="trend chart">
      {[0.25, 0.5, 0.75].map((f) => (
        <line key={f} x1={0} x2={width} y1={height * f} y2={height * f} stroke="var(--border)" strokeWidth={1} />
      ))}
      {series.map((s, si) => {
        const pts = s.points
          .map((v, i) => `${(i / Math.max(1, n - 1)) * (width - 40) + 20},${height - 20 - ((v - lo) / span) * (height - 40)}`)
          .join(' ')
        return <polyline key={s.label} points={pts} fill="none" stroke={colors[si % colors.length]} strokeWidth={2} />
      })}
      {series.map((s, si) => (
        <text key={'l' + s.label} x={8} y={14 + si * 14} fill={colors[si % colors.length]} fontSize={11}>
          {s.label}
        </text>
      ))}
    </svg>
  )
}

// ---------- diff viewer ----------

export function DiffViewer({ diff }: { diff: string }) {
  if (!diff.trim()) return <EmptyState hint="No workspace changes." />
  return (
    <pre className="diff" data-testid="diff-viewer">
      {diff.split('\n').map((line, i) => (
        <span
          key={i}
          className={
            line.startsWith('+') && !line.startsWith('+++')
              ? 'add'
              : line.startsWith('-') && !line.startsWith('---')
                ? 'del'
                : line.startsWith('@@')
                  ? 'hunk'
                  : ''
          }
        >
          {line}
          {'\n'}
        </span>
      ))}
    </pre>
  )
}

// ---------- trace timeline / tool-call viewer ----------

export interface TraceLine {
  seq: number
  type: string
  tool?: string
  status?: string
  duration_ms?: number
  summary?: string
}

export function TraceTimeline({ events }: { events: TraceLine[] }) {
  if (events.length === 0) return <EmptyState hint="No trace events." />
  return (
    <ol className="timeline">
      {events.map((e) => (
        <li key={e.seq} className={`tl-${e.type}`}>
          <span className="tl-seq">#{e.seq}</span>
          <span className="tl-type">{e.type}</span>
          {e.tool && <code>{e.tool}</code>}
          {e.status && <Badge kind={e.status === 'ok' ? 'ok' : e.status === 'denied' ? 'warn' : 'bad'}>{e.status}</Badge>}
          {typeof e.duration_ms === 'number' && <span className="tl-ms">{e.duration_ms.toFixed(1)} ms</span>}
          {e.summary && <span className="tl-summary">{e.summary}</span>}
        </li>
      ))}
    </ol>
  )
}

// ---------- resilience & access states ----------

import { Component, useEffect as _useEffect, useState as _useState } from 'react'
import type { ErrorInfo } from 'react'

/** Route-level error boundary: a crash in one page never blanks the app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Local diagnostics only — never reported anywhere.
    console.error('Route render failed:', error.message, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="state error" role="alert">
          <strong>This page hit an unexpected error.</strong>{' '}
          <button type="button" onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      )
    }
    return this.props.children
  }
}

/** Banner shown when the browser reports offline connectivity. */
export function OfflineBanner({ online }: { online: boolean }) {
  if (online) return null
  return (
    <div className="offline-banner" role="status">
      You are offline — showing cached/static data. Live server features are unavailable.
    </div>
  )
}

export function useOnlineStatus(): boolean {
  const [online, setOnline] = _useState(() => navigator.onLine)
  _useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])
  return online
}

export function NoPermission({ hint }: { hint?: string }) {
  return (
    <div className="state" role="alert">
      <strong>No permission.</strong> {hint ?? 'Your account/token lacks the required role for this action.'}
    </div>
  )
}

export function DemoBadge() {
  return <Badge kind="warn">DEMO DATA</Badge>
}

// ---------- virtualized list for large traces ----------

/** Windowed list: renders only the visible slice so multi-thousand-event
 * traces scroll smoothly instead of freezing the browser. */
export function VirtualList<T>({
  items,
  itemHeight,
  height,
  render,
  ariaLabel,
}: {
  items: T[]
  itemHeight: number
  height: number
  render: (item: T, index: number) => ReactNode
  ariaLabel?: string
}) {
  const [scrollTop, setScrollTop] = _useState(0)
  const total = items.length * itemHeight
  const start = Math.max(0, Math.floor(scrollTop / itemHeight) - 4)
  const visibleCount = Math.ceil(height / itemHeight) + 8
  const end = Math.min(items.length, start + visibleCount)
  const slice = items.slice(start, end)
  return (
    <div
      className="virtual-list"
      style={{ height, overflowY: 'auto', position: 'relative' }}
      onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
      role="list"
      aria-label={ariaLabel}
    >
      <div style={{ height: total, position: 'relative' }}>
        <ol style={{ position: 'absolute', top: start * itemHeight, left: 0, right: 0, margin: 0, padding: 0, listStyle: 'none' }}>
          {slice.map((item, i) => (
            <li key={start + i} style={{ minHeight: itemHeight }} role="listitem">
              {render(item, start + i)}
            </li>
          ))}
        </ol>
      </div>
    </div>
  )
}
