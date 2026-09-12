// Immutable hash-chained audit log view.

import { isServerMode, listAudit, type AuditEntry } from '../../api'
import { DataTable, DemoBadge, ErrorState, Loading, type Column } from '../../components'
import { useAsync } from '../../api'
import { DEMO_AUDIT } from '../demoData'
import { ServerGate, ServerStatus } from './shared'

const AUDIT_COLS: Column<AuditEntry>[] = [
  { key: 'seq', header: '#', value: (a) => a.seq, numeric: true },
  { key: 'at', header: 'When (UTC)', value: (a) => a.timestamp },
  { key: 'actor', header: 'Actor', value: (a) => a.actor },
  { key: 'action', header: 'Action', value: (a) => a.action },
  { key: 'target', header: 'Target', value: (a) => a.target },
  // Truncated for width; the full digest is in the API response, and a reader
  // checking a chain by hand is using that rather than reading it off a table.
  { key: 'hash', header: 'Chain hash', value: (a) => a.entry_hash.slice(0, 16) },
]

/**
 * This page is written out rather than using `ConsoleData` because it has one
 * thing to say that a table cannot: **whether the chain still verifies.**
 *
 * The old version promised "tampering breaks verification" in its own prose and
 * then showed a list of rows without ever saying whether verification had
 * passed. A hash chain whose verdict is not displayed is a more expensive text
 * file. The verdict goes above the table, because it is the reason to look.
 */
export function AuditLogPage() {
  const live = isServerMode()
  const state = useAsync(
    () =>
      live
        ? listAudit()
        : Promise.resolve({ rows: DEMO_AUDIT, chainVerified: true }),
    [live],
  )

  return (
    <ServerGate>
      <section>
        <h1>Audit log</h1>
        <p>
          <ServerStatus />{' '}
          <span className="muted">
            Hash-chained events for privileged actions and publication decisions. Each entry commits
            to its predecessor, so an entry edited or removed after the fact breaks every hash after
            it.
          </span>
        </p>
        {!live && <DemoBadge />}
        {state.loading && <Loading />}
        {state.error && <ErrorState message={state.error} />}
        {state.data && (
          <>
            <p
              className={state.data.chainVerified ? 'notice ok' : 'notice bad'}
              role="status"
              aria-live="polite"
            >
              {state.data.chainVerified ? (
                <>
                  <strong>Chain verified.</strong> Every entry below commits to the one before it,
                  recomputed from the entries themselves rather than taken on trust.
                </>
              ) : (
                <>
                  <strong>Chain broken.</strong> At least one entry does not match the hash its
                  successor commits to. Treat this log as evidence of tampering, not as a record.
                </>
              )}
            </p>
            <DataTable
              rows={state.data.rows}
              columns={AUDIT_COLS}
              emptyHint="No audit events recorded yet. Privileged actions append here as they happen."
            />
          </>
        )}
      </section>
    </ServerGate>
  )
}
