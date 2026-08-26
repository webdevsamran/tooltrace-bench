// Task Authoring Studio: YAML draft editor with client-side lint pre-checks
// mirroring `tooltrace lint`. The authoritative check remains the CLI/server
// linter; this gives instant feedback while authoring.

import { useMemo, useState } from 'react'
import { EmptyState } from '../../components'
import { ServerGate, ServerStatus } from './shared'

export interface StudioIssue {
  level: 'error' | 'warn'
  message: string
}

/** Client-side pre-validation mirroring tooltrace task-lint rules.
 * The authoritative check remains the CLI/server linter; this gives instant
 * feedback while authoring. */
export function validateTaskDraft(yaml: string): StudioIssue[] {
  const issues: StudioIssue[] = []
  if (!yaml.trim()) return [{ level: 'error', message: 'Task draft is empty.' }]
  if (!/^id:/m.test(yaml)) issues.push({ level: 'error', message: 'Missing required field: id.' })
  if (!/^version:/m.test(yaml)) issues.push({ level: 'error', message: 'Missing required field: version.' })
  if (!/^objective:/m.test(yaml)) issues.push({ level: 'error', message: 'Missing required field: objective.' })
  if (/curl |wget |http:\/\/(?!localhost|127\.)/i.test(yaml))
    issues.push({ level: 'warn', message: 'Possible uncontrolled network use — declare network_policy explicitly.' })
  if (!/assertions?:/.test(yaml))
    issues.push({ level: 'error', message: 'No assertions block: tasks must be scoreable deterministically.' })
  if (/judge|llm_score|model_grade/i.test(yaml))
    issues.push({ level: 'warn', message: 'Model-judge scoring detected — keep deterministic scorers primary and report judge dependency separately.' })
  if (!/cleanup|teardown/i.test(yaml))
    issues.push({ level: 'warn', message: 'No cleanup step declared — lint requires sandbox teardown for side-effecting tasks.' })
  if (!/seed|deterministic/i.test(yaml))
    issues.push({ level: 'warn', message: 'No explicit seed/determinism note — fixtures should be reproducible byte-for-byte.' })
  return issues
}

const STUDIO_SAMPLE = `id: fileops/demo-new-task
version: 1.0.0
objective: Replace FOO with BAR in notes.txt using patch_file.
network_policy: disabled
deterministic_seed: 7
starting_workspace:
  notes.txt: "value=FOO"
assertions:
  - type: file_contains
    params: { path: notes.txt, text: BAR }
    weight: 1.0`

export function TaskStudioPage() {
  const [draft, setDraft] = useState(STUDIO_SAMPLE)
  const issues = useMemo(() => validateTaskDraft(draft), [draft])
  const errors = issues.filter((i) => i.level === 'error')
  const warns = issues.filter((i) => i.level === 'warn')
  const assertions = [...draft.matchAll(/-\s*type:\s*(\w+)/g)].map((m) => m[1])

  return (
    <ServerGate>
      <section>
        <h1>Task Authoring Studio</h1>
        <p>
          <ServerStatus /> <span className="muted">
            Draft a task pack YAML; this validation is a fast pre-check — the authoritative gates are{' '}
            <code>tooltrace validate</code>, <code>tooltrace lint</code> and <code>tooltrace dry-run</code>.
          </span>
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '1rem' }}>
          <div>
            <label htmlFor="studio-editor" style={{ display: 'block' }}>
              Task draft (YAML)
              <textarea id="studio-editor" value={draft} onChange={(e) => setDraft(e.target.value)}
                rows={16} spellCheck={false}
                style={{ width: '100%', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '.85rem' }} />
            </label>
          </div>
          <div>
            <h2 style={{ marginTop: 0 }}>Validation ({errors.length} errors · {warns.length} warnings)</h2>
            {issues.length === 0 ? (
              <p className="badge badge-ok">All pre-checks passed.</p>
            ) : (
              <ul aria-label="Validation findings">
                {issues.map((i, ix) => (
                  <li key={ix}>
                    <span className={`badge ${i.level === 'error' ? 'badge-bad' : 'badge-warn'}`}>{i.level}</span> {i.message}
                  </li>
                ))}
              </ul>
            )}
            <h2>Assertion workflow</h2>
            {assertions.length === 0 ? (
              <EmptyState hint="No assertions parsed." />
            ) : (
              <ol className="timeline" aria-label="Assertion graph">
                {assertions.map((a, i) => (
                  <li key={i}><span className="tl-seq">{i + 1}</span><span className="tl-type">{a}</span></li>
                ))}
              </ol>
            )}
            <h2>Deterministic vs judged scoring</h2>
            <p className="muted">
              All built-in scorers are deterministic executable assertions. Model judges, when configured,
              are reported separately with disagreement stats — never silently averaged into pass/fail.
            </p>
            <h2>Next steps</h2>
            <p className="card">
              <code>tooltrace validate --path mypack</code> → <code>tooltrace lint --path mypack</code> →{' '}
              <code>tooltrace dry-run --task …</code> (no model needed) → submit via pull request.
            </p>
          </div>
        </div>
      </section>
    </ServerGate>
  )
}
