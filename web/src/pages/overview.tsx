import { Link } from 'react-router-dom'
import { getIndex, getResults, useAsync } from '../api'
import { BarChart, EmptyState, ErrorState, Loading } from '../components'

export function HomePage() {
  const idx = useAsync(getIndex)
  const results = useAsync(getResults)
  if (idx.loading || results.loading) return <Loading />
  if (idx.error) return <ErrorState message={idx.error} />

  const byTask = new Map<string, { total: number; ok: number }>()
  for (const r of results.data ?? []) {
    const e = byTask.get(r.task_id) ?? { total: 0, ok: 0 }
    e.total += 1
    if (r.success) e.ok += 1
    byTask.set(r.task_id, e)
  }
  const chart = [...byTask.entries()]
    .map(([label, v]) => ({ label, value: v.total ? v.ok / v.total : 0 }))
    .sort((a, b) => b.value - a.value)

  return (
    <div>
      <section className="hero">
        <h1>ToolTrace Bench</h1>
        <p>
          Vendor-neutral, reproducible benchmarking of AI agents across coding,
          tool use, file operations, multi-step workflows, failure recovery,
          latency, cost and reliability. Local-first and offline friendly.
        </p>
        <div className="hero-actions">
          <Link className="btn" to="/leaderboard">View leaderboard</Link>
          <Link className="btn ghost" to="/methodology">Read methodology</Link>
        </div>
      </section>
      <section className="grid stats">
        <div className="card"><strong>{idx.data?.counts.tasks ?? '–'}</strong><span>tasks</span></div>
        <div className="card"><strong>{idx.data?.counts.packs ?? '–'}</strong><span>task packs</span></div>
        <div className="card"><strong>{idx.data?.counts.results ?? '–'}</strong><span>validated results</span></div>
        <div className="card"><strong>{idx.data?.counts.agents ?? '–'}</strong><span>agents</span></div>
      </section>
      <section>
        <h2>Success rate by task</h2>
        {chart.length === 0 ? (
          <EmptyState hint="Run `tooltrace benchmark` and regenerate web data to populate this chart." />
        ) : (
          <BarChart data={chart} max={1} format={(v) => `${(v * 100).toFixed(0)}%`} />
        )}
      </section>
      <section>
        <h2>What it answers</h2>
        <ul className="answers">
          <li>Can an agent actually finish a task — and does it use tools correctly?</li>
          <li>Can it recover from failed tools or commands?</li>
          <li>How many steps and tool calls does it need? Does it make destructive changes?</li>
          <li>Is it consistent across repeated runs? How much time does it consume?</li>
          <li>Does reliability degrade with longer context?</li>
        </ul>
      </section>
    </div>
  )
}

export function MethodologyPage() {
  return (
    <article>
      <h1>Methodology</h1>
      <p>
        Every result on this site comes from a validated <code>.tooltrace</code>{' '}
        bundle produced by the framework itself. Nothing is hand-edited; if a
        bundle fails checksum verification it is excluded.
      </p>
      <h2>Deterministic scoring</h2>
      <p>
        Tasks are scored by executable assertions: tests passing, file/AST
        checks, JSON schema validation, command exit codes, git diff
        constraints, API state and data equality. A weighted composite score is
        computed transparently from per-assertion weights.
      </p>
      <h2>Reliability metrics</h2>
      <ul>
        <li>success / partial-success rate with Wilson confidence intervals</li>
        <li>steps, tool calls, failed tool calls, invalid tool use, repeated calls</li>
        <li>unnecessary-change count and workspace violations</li>
        <li>wall/model/tool time, p50/p95 latency</li>
        <li>token usage when the adapter provides it; cost only when explicitly reported</li>
        <li>run-to-run consistency across repeated runs</li>
      </ul>
      <h2>Perturbations & recovery</h2>
      <p>
        Controlled faults (transient tool failure, non-zero exit, moved files,
        mock-API errors, delays, ambiguous errors, irrelevant files) measure
        whether an agent recovers. No offensive security payloads are used.
      </p>
      <h2>Fair comparison rules</h2>
      <p>
        Only runs sharing identical task-protocol, trace-schema and
        result-schema versions are ever compared. Trust states (LOCAL →
        COMMUNITY_VALIDATED → REPRODUCED → MAINTAINER_VERIFIED) are recorded
        per bundle and never implied without evidence.
      </p>
    </article>
  )
}

export function DocsPage() {
  return (
    <article>
      <h1>Docs</h1>
      <h2>60-second quickstart</h2>
      <pre>{`pip install -e .
tooltrace doctor
tooltrace run --task file-editing/fix-config-typo --agent scripted --out results/
tooltrace benchmark --runs 3 --out results/
tooltrace report --bundles results/ --format html --output report.html`}</pre>
      <h2>Authoring tasks</h2>
      <pre>{`tooltrace task scaffold --pack-dir my-pack --task-id my-pack/my-task
tooltrace task validate --path my-pack
tooltrace task test --path my-pack`}</pre>
      <h2>Comparison & regression gates</h2>
      <pre>{`tooltrace baseline --name main --bundle results/<bundle>.tooltrace
tooltrace regression --baseline <b> --current <c> \\
  --thresholds '{"score":{"min_delta":-0.05},"wall_ms":{"max_increase_pct":20}}'`}</pre>
      <p>
        Full documentation lives in the repository: README.md, ARCHITECTURE.md,
        docs/threat-model.md and schemas/.
      </p>
    </article>
  )
}

export function ContributorsPage() {
  return (
    <article>
      <h1>Contributors</h1>
      <p>
        Original creator, founder and lead maintainer:{' '}
        <a href="https://github.com/webdevsamran">@webdevsamran</a>.
      </p>
      <p>
        Contributors are listed in AUTHORS and MAINTAINERS in the repository.
        Good first issues focus on task packs, agent adapters, deterministic
        scorers, sandbox providers, frontend views and analysis algorithms —
        see CONTRIBUTING.md to get started.
      </p>
    </article>
  )
}

export function AboutPage() {
  return (
    <article>
      <h1>About</h1>
      <p>
        ToolTrace Bench occupies a clear niche beside serious coding-agent
        benchmarks: a vendor-neutral, local-friendly reliability laboratory
        emphasizing repeatability, tool behavior, failure recovery, traces and
        CI regressions rather than leaderboard hype.
      </p>
      <p>
        The core is fully open source (Apache-2.0). Future optional enterprise
        concepts (private results, org dashboards, worker fleets, SSO/RBAC,
        audit logs) are documented but never cripple OSS basics.
      </p>
      <p>Licensed Apache-2.0 · Created by @webdevsamran.</p>
    </article>
  )
}