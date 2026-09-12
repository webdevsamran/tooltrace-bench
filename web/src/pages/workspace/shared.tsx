// Shared building blocks for the self-hosted team console pages.
// Every page renders inside a ServerGate: either a live server connection
// or an explicitly-labeled DEMO preview — demo rows never leak into data.

import { useState } from 'react'
import { getServerUrl, isServerMode, setServerToken, setServerUrl, useAsync } from '../../api'
import { DataTable, DemoBadge, ErrorState, Loading, type Column } from '../../components'

/** Gate shown when no self-hosted server is configured. */
export function ServerGate({ children }: { children: React.ReactNode }) {
  const [demo, setDemo] = useState(false)
  const [url, setUrl] = useState('')
  const [token, setToken] = useState('')

  if (isServerMode() || demo) return <>{children}</>
  return (
    <div className="state" data-testid="server-gate">
      <h2>Connect to a ToolTrace server</h2>
      <p className="muted">
        These pages manage a self-hosted coordinator (<code>tooltrace server</code>). Connect to
        your deployment, or preview the console with clearly-labeled demo fixtures.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          setServerUrl(url.trim())
          setServerToken(token.trim())
        }}
      >
        <label className="field">Server URL{' '}
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://localhost:8471" />
        </label>
        <label className="field">API token (optional){' '}
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="ttb_…" autoComplete="off" />
        </label>
        <button className="btn" type="submit">Connect</button>{' '}
        <button className="btn ghost" type="button" onClick={() => setDemo(true)}>Preview with DEMO data</button>
      </form>
    </div>
  )
}

/** Connection badge: DEMO marker in static mode, server URL otherwise.
 * Exported for the other workspace console modules. */
export function ServerStatus() {
  if (!isServerMode()) return <DemoBadge />
  return <span className="badge badge-info">{getServerUrl()}</span>
}

/**
 * The one place the demo rule lives.
 *
 * Every workspace page used to render its `DEMO_*` constant unconditionally,
 * with the DEMO badge as the only thing gated on `isServerMode()` -- so a
 * connected administrator saw invented users, an invented approval queue and
 * three invented workers, *without* the badge that would have said so. The
 * comment at the top of this file has always claimed "demo rows never leak into
 * data". This is what makes that true.
 *
 * Connected: fetch, and show what came back, including the server's own note
 * about why a list is the length it is -- "no webhooks" and "webhooks are not
 * configured here" are different facts and an empty table hides the difference.
 *
 * Not connected: the demo fixture, always badged, never silently.
 *
 * One component rather than a rule in a contributing guide, because a rule has
 * to be remembered and this cannot be forgotten: a page that wants a table has
 * to hand over both halves.
 */
export function ConsoleData<T>({
  load,
  demo,
  columns,
  emptyHint,
  children,
}: {
  /** Server-mode fetch. Only called when a server is actually connected. */
  load: () => Promise<{ rows: T[]; note?: string }>
  /** Shown only in DEMO mode, and only with the badge. */
  demo: T[]
  columns: Column<T>[]
  emptyHint: string
  /** Rendered under the table with the live rows, for pages that add a chart. */
  children?: (rows: T[], live: boolean) => React.ReactNode
}) {
  const live = isServerMode()
  // The hook runs either way -- hooks cannot be conditional -- and resolves to
  // an empty list in demo mode rather than calling a server that is not there.
  const state = useAsync<{ rows: T[]; note?: string }>(
    () => (live ? load() : Promise.resolve({ rows: [] as T[] })),
    [live],
  )

  if (!live) {
    return (
      <>
        <DemoBadge />
        <DataTable rows={demo} columns={columns} emptyHint={emptyHint} />
        {children?.(demo, false)}
      </>
    )
  }
  if (state.loading) return <Loading />
  if (state.error) return <ErrorState message={state.error} />
  const rows = state.data?.rows ?? []
  return (
    <>
      {state.data?.note && (
        <p className="notice" role="note">
          {state.data.note}
        </p>
      )}
      <DataTable rows={rows} columns={columns} emptyHint={emptyHint} />
      {children?.(rows, true)}
    </>
  )
}
