// Retention, backup/export and connection settings.

import { useState } from 'react'
import { apiGet, apiPost, isServerMode } from '../../api'
import { DemoBadge, ErrorState } from '../../components'
import { useToast } from '../../motion'
import { ServerGate, ServerStatus } from './shared'

/**
 * This page used to be three prose cards, and two of them were false.
 *
 * It told operators that retention was "configurable with deletion of expired
 * records" -- `apply_retention` existed, was tested, and had no caller anywhere
 * outside its own tests. And it told them that "self-hosted metadata and
 * artifact references support backup/restore", linking to
 * `docs/self-hosting.md#backup-and-restore`, an anchor that did not exist, for
 * a feature `docs/feature-status.md` graded **N: no backup or restore code
 * ships**. Two shipped artifacts of this project contradicted each other and
 * the console was the one lying.
 *
 * Both are now buttons that call endpoints that do the thing.
 */
export function RetentionSettingsPage() {
  const live = isServerMode()
  const { push } = useToast()
  const [maxAgeDays, setMaxAgeDays] = useState(90)
  const [preview, setPreview] = useState<{ deleted: string[]; statement: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const run = async (dryRun: boolean) => {
    setError(null)
    try {
      const result = await apiPost<{ deleted: string[]; statement: string }>(
        '/api/v1/retention',
        { max_age_days: maxAgeDays, dry_run: dryRun },
      )
      setPreview(result)
      push(result.statement, dryRun ? 'info' : 'warn')
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      setError(message)
      push(message, 'bad')
    }
  }

  const download = async () => {
    setError(null)
    try {
      const snapshot = await apiGet<Record<string, unknown>>('/api/v1/export')
      // Handed to the browser rather than written by the server: the operator
      // chooses where their own backup lands, and the server never needs a
      // writable path outside its own working directory.
      const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `tooltrace-snapshot-${new Date().toISOString().slice(0, 10)}.json`
      link.click()
      URL.revokeObjectURL(url)
      push('Snapshot downloaded.', 'ok')
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      setError(message)
      push(message, 'bad')
    }
  }

  return (
    <ServerGate>
      <section>
        <h1>Retention &amp; settings</h1>
        <p>
          <ServerStatus />
        </p>
        {!live && <DemoBadge />}
        {error && <ErrorState message={error} />}

        <div className="card">
          <strong>Artifact retention</strong>
          <p className="muted">
            Deletes experiment records older than the window, except those under a legal hold.{' '}
            <strong>Administrative only</strong> — deleting on a schedule is not a
            legal-compliance determination, and this console will not call it one.
          </p>
          <label className="field">
            Keep for (days){' '}
            <input
              type="number"
              min={1}
              value={maxAgeDays}
              onChange={(e) => setMaxAgeDays(Number(e.target.value))}
            />
          </label>{' '}
          {/* Preview first, and it is the primary button. A deletion control
              whose default is to delete is one somebody presses while
              exploring. */}
          <button className="btn" type="button" onClick={() => void run(true)} disabled={!live}>
            Preview
          </button>{' '}
          <button
            className="btn ghost"
            type="button"
            onClick={() => void run(false)}
            disabled={!live || !preview || preview.deleted.length === 0}
          >
            Delete {preview ? `${preview.deleted.length}` : ''} record(s)
          </button>
          {preview && <p className="muted">{preview.statement}</p>}
        </div>

        <div className="card">
          <strong>Backup</strong>
          <p className="muted">
            Downloads everything this server holds that exists only in memory — users, policies,
            quotas, approvals, experiments and the audit chain — as one JSON snapshot. Restore it
            with <code>POST /api/v1/import</code>; the restore is destructive by design, refuses a
            snapshot from a version it does not understand rather than restoring the half it
            recognises, and <strong>re-verifies the audit chain</strong> instead of trusting it.
          </p>
          <p className="muted">
            <code>.tooltrace</code> bundles are <em>not</em> in the snapshot. They are checksummed
            files on a disk, and a backup tool that copied them into a JSON document would be a
            slower <code>cp</code> with no extra safety.
          </p>
          <button className="btn" type="button" onClick={() => void download()} disabled={!live}>
            Download snapshot
          </button>
        </div>

        <div className="card">
          <strong>Connection</strong>
          <p className="muted">
            The server URL and token are stored only in this browser. The token is sent solely as a
            Bearer header to your own server — never logged, never embedded in a shared URL.
          </p>
        </div>
      </section>
    </ServerGate>
  )
}
