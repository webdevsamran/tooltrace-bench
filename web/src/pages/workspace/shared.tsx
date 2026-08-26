// Shared building blocks for the self-hosted team console pages.
// Every page renders inside a ServerGate: either a live server connection
// or an explicitly-labeled DEMO preview — demo rows never leak into data.

import { useState } from 'react'
import { getServerUrl, isServerMode, setServerToken, setServerUrl } from '../../api'
import { DemoBadge } from '../../components'

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
