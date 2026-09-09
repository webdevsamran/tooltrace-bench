import { Link } from 'react-router-dom'
import {
  getEvidence,
  getSecurity,
  useAsync,
  type RateBlock,
  type SecurityRun,
} from '../api'
import { EmptyState, ErrorState, Loading } from '../components'

/**
 * The two views a reader who is not a benchmark author comes for: a compliance
 * reviewer, and someone deciding whether an agent is safe to give tools to.
 *
 * Both are built entirely from data this project already produced and had never
 * shown anyone — `tooltrace.analysis.evidence` and `tooltrace.metrics.security`
 * were reachable from the CLI and from nowhere else.
 *
 * Both pages are constrained by the same rule, which is the whole reason they
 * are worth building: **they must be more careful about what they do not say
 * than about what they do.** An evidence dossier that renders as a compliance
 * verdict, or a 0% attack-success rate over four attempts that renders as a
 * green badge, would be worse than showing nothing. The machine origin of the
 * number lends it authority it has not earned.
 */

// --- shared -----------------------------------------------------------------

function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`
}

/**
 * A rate is never shown alone. The interval and the attempt count are what
 * make it readable: 0% of 4 attempts has an upper bound near 50%, and a reader
 * shown only "0%" has been misled by omission.
 */
export function RateReadout({ block, label }: { block: RateBlock; label: string }) {
  const rate = block.attack_success_rate
  return (
    <div className="rate-readout">
      <span className="rate-label">{label}</span>
      <span className={`rate-value${rate ? ' is-bad' : ''}`}>{percent(rate)}</span>
      <span className="rate-detail">
        {block.attacks_succeeded} of {block.attempts} attempt
        {block.attempts === 1 ? '' : 's'}
        {block.ci95 && (
          <>
            {' · 95% CI '}
            <span className="num">
              {percent(block.ci95[0])}–{percent(block.ci95[1])}
            </span>
          </>
        )}
      </span>
      {block.sample_is_small && (
        <span className="rate-caveat">
          Fewer than 30 attempts. Not a stable measurement — read the interval, not the rate.
        </span>
      )}
    </div>
  )
}

// --- security posture (F134) ------------------------------------------------

export function SecurityPosturePage() {
  const posture = useAsync(getSecurity)
  if (posture.loading) return <Loading />
  // A dataset generated before this index existed has no security.json. That is
  // an older dataset, not an error, and it must not blank the page.
  if (posture.error)
    return (
      <div>
        <h1>Security posture</h1>
        <EmptyState hint="This dataset carries no security index. Regenerate it with scripts/generate_web_data.py." />
      </div>
    )

  const data = posture.data
  if (!data || data.attempts === 0) {
    return (
      <div>
        <h1>Security posture</h1>
        <EmptyState hint="No adversarial runs in this dataset. Run the security/ packs to measure resistance." />
      </div>
    )
  }

  const classes = Object.entries(data.by_class).sort((a, b) => b[1].attempts - a[1].attempts)
  const agents = Object.entries(data.by_agent).sort((a, b) => a[0].localeCompare(b[0]))

  return (
    <div>
      <h1>Security posture</h1>
      <p className="muted">
        Attack success rate — the share of adversarial attempts that got through. The scorers
        score the <em>defence</em>, so this is the inversion, derived in one place so the CLI and
        this page cannot disagree.
      </p>

      <p className="callout callout-warn">
        <strong>An attack that was resisted is not an attack that cannot succeed.</strong> This
        measures the payloads in this project&apos;s task packs, run against this agent, on this
        dataset. It does not generalise to payloads the packs do not contain, and a rate over a
        handful of attempts is closer to an anecdote than a measurement.
      </p>

      <section className="card">
        <h2>Overall</h2>
        <RateReadout block={data} label="Attack success rate" />
      </section>

      <h2>By attack class</h2>
      <div className="grid">
        {classes.map(([name, block]) => (
          <section className="card" key={name}>
            <h3>{name.replace(/_/g, ' ')}</h3>
            <RateReadout block={block} label="Succeeded" />
          </section>
        ))}
      </div>

      {agents.length > 1 && (
        <>
          <h2>By agent</h2>
          <div className="grid">
            {agents.map(([name, block]) => (
              <section className="card" key={name}>
                <h3>{name}</h3>
                <RateReadout block={block} label="Succeeded" />
              </section>
            ))}
          </div>
        </>
      )}

      <h2>Attempts</h2>
      <p className="muted">
        Oldest first, so a change in resistance over time is visible rather than averaged away.
      </p>
      <ol className="attempt-list">
        {data.runs.map((run) => (
          <AttemptRow key={run.bundle} run={run} />
        ))}
      </ol>
    </div>
  )
}

function AttemptRow({ run }: { run: SecurityRun }) {
  return (
    <li className={run.attack_succeeded ? 'attempt is-bad' : 'attempt is-ok'}>
      {/* The word, not only the colour: this row's whole meaning is carried by
          one bit, and a bit encoded as a hue reaches nobody who cannot see it. */}
      <span className="attempt-verdict">{run.attack_succeeded ? 'succeeded' : 'resisted'}</span>
      <span className="attempt-class">{run.attack_class.replace(/_/g, ' ')}</span>
      <Link to={`/results/${encodeURIComponent(run.bundle)}`}>
        <code>{run.task_id}</code>
      </Link>
      <span className="muted">{run.agent}</span>
      {run.owasp && <span className="attempt-owasp">{run.owasp}</span>}
    </li>
  )
}

// --- evidence dossier (F133) ------------------------------------------------

export function EvidencePage() {
  const dossier = useAsync(getEvidence)
  if (dossier.loading) return <Loading />
  if (dossier.error)
    return (
      <div>
        <h1>Evidence</h1>
        <EmptyState hint="This dataset carries no evidence dossier. Regenerate it with scripts/generate_web_data.py." />
      </div>
    )
  const data = dossier.data
  if (!data) return <ErrorState message="No dossier." />

  const unverified = data.runs.filter((r) => !r.verified)

  return (
    <div>
      <h1>Evidence</h1>

      {/* First thing on the page, before any number. A reader who scrolls past
          everything else must still have read this. */}
      <p className="callout callout-warn">
        <strong>This is evidence, not a compliance determination.</strong> {data.statement}
      </p>

      <section className="stats" aria-label="Dossier summary">
        <div className="stat">
          <span className="stat-label">Runs recorded</span>
          <span className="stat-value">{data.runs.length}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Checksums verified</span>
          <span className="stat-value">
            {data.runs.length - unverified.length} / {data.runs.length}
          </span>
        </div>
        <div className="stat">
          <span className="stat-label">Chain head</span>
          <span className="stat-value mono-sm">{data.chain_head.slice(0, 12)}…</span>
        </div>
        <div className="stat">
          <span className="stat-label">Dated</span>
          <span className="stat-value mono-sm">{data.generated_at.slice(0, 10)}</span>
        </div>
      </section>

      {unverified.length > 0 && (
        <p className="callout callout-bad">
          <strong>{unverified.length} bundle(s) failed checksum verification</strong> and are
          listed below as such. A dossier that hid them would be the opposite of evidence.
        </p>
      )}

      <h2>Obligations</h2>
      <p className="muted">
        Article references are to the EU AI Act obligations for high-risk systems, included so a
        reviewer can find the relevant text. They are pointers, not legal advice.
      </p>
      {data.obligations.map((obligation) => (
        <section className="card obligation" key={obligation.article}>
          <h3>
            {obligation.article} — {obligation.title}
          </h3>
          <div className="obligation-cols">
            <div>
              <h4 className="obligation-head">Evidenced here</h4>
              <ul>
                {obligation.evidence.length ? (
                  obligation.evidence.map((item) => <li key={item}>{item}</li>)
                ) : (
                  <li className="muted">Nothing in this dossier speaks to this obligation.</li>
                )}
              </ul>
            </div>
            <div>
              {/* Deliberately the same visual weight as the column beside it.
                  Gaps shown smaller, or folded away, would turn the dossier
                  into the claim it exists to avoid making. */}
              <h4 className="obligation-head">Not evidenced here</h4>
              <ul className="gaps">
                {obligation.gaps.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </div>
        </section>
      ))}

      <h2>Chain of custody</h2>
      <p className="muted">
        Each entry commits to the one before it, so a removed or reordered run is detectable and
        not only a modified one. Checksums are tamper-<em>evident</em>, not tamper-proof: they
        detect modification and do not establish who produced a bundle.
      </p>
      <div className="table-scroll">
        <table className="evidence-table">
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Task</th>
              <th scope="col">Agent</th>
              <th scope="col">Verified</th>
              <th scope="col">Outcome</th>
              <th scope="col">Harness</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((run) => (
              <tr key={run.bundle}>
                <td>
                  <Link to={`/results/${encodeURIComponent(run.bundle)}`}>
                    <code>{run.run_id || run.bundle}</code>
                  </Link>
                </td>
                <td>
                  {run.task_id}
                  <span className="muted">@{run.task_version}</span>
                </td>
                <td>{run.agent}</td>
                <td className={run.verified ? 'ok' : 'bad'}>{run.verified ? 'yes' : 'NO'}</td>
                <td>{run.success ? 'pass' : (run.failure_reason ?? 'fail')}</td>
                <td className="mono-sm">{run.framework_version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
