// Group failed runs into clusters, and rank the clusters by what is worth
// looking at first.
//
// The failure view this replaces was a bar chart of twelve category names. That
// answers "how many runs hit a policy violation" and nothing else. The question
// a reader actually has is "is this one bug or twelve", and a category cannot
// answer it: two runs can share `execution` and have nothing else in common,
// while two runs that both died calling `patch_file` with the same rule are
// almost certainly the same defect.
//
// So a cluster keys on the *signature* — reason, the rule that matched, and the
// tool the failure was attributed to. That is as specific as the attribution
// data supports and no more; inventing a finer key (arguments, timings) would
// split one defect across several clusters and read as breadth that isn't
// there.
//
// This is deliberately plain data-in/data-out. The ranking rules below are the
// opinionated part of the feature and they are worth testing without mounting a
// component to do it.

import type { ResultRow } from '../api'

export interface FailureCluster {
  /** Stable, URL-safe identity so a cluster can be linked to. */
  id: string
  reason: string
  rule: string
  /** Null when the failure is not attributable to a specific tool call. */
  tool: string | null
  runs: ResultRow[]
  /** Distinct tasks touched. A cluster spanning many tasks is systemic. */
  tasks: string[]
  /** Distinct agents touched. One agent means it may not be the harness. */
  agents: string[]
  /** The seq the failure is attributed to, when every run agrees on one. */
  representativeSeq: number | null
  /** A human-readable detail from the first run, for the cluster summary. */
  detail: string
}

/** Runs with no attribution at all still need somewhere to go. */
export const UNATTRIBUTED_RULE = '(unattributed)'

function signature(row: ResultRow): { reason: string; rule: string; tool: string | null } {
  const step = row.failure_step
  return {
    reason: row.failure_reason,
    // An older index has no `failure_step` at all. That is a real state — the
    // data was generated before attribution existed — and it must read as
    // "not attributed", never as a rule named after the empty string.
    rule: step?.rule || UNATTRIBUTED_RULE,
    tool: step?.tool ?? null,
  }
}

function idFor(sig: { reason: string; rule: string; tool: string | null }): string {
  return [sig.reason, sig.rule, sig.tool ?? '-']
    .map((part) => part.replace(/[^a-zA-Z0-9_.-]+/g, '-'))
    .join('~')
}

/**
 * Cluster failed runs by signature, largest first.
 *
 * Ties break on the number of distinct tasks affected: between two clusters of
 * equal size, the one spanning more tasks is the more systemic problem and the
 * better thing to look at first.
 */
export function clusterFailures(rows: ResultRow[]): FailureCluster[] {
  const byId = new Map<string, FailureCluster>()

  for (const row of rows) {
    if (row.success) continue
    const sig = signature(row)
    const id = idFor(sig)
    const existing = byId.get(id)
    if (existing) {
      existing.runs.push(row)
      continue
    }
    byId.set(id, {
      id,
      reason: sig.reason,
      rule: sig.rule,
      tool: sig.tool,
      runs: [row],
      tasks: [],
      agents: [],
      representativeSeq: null,
      detail: row.failure_step?.detail ?? '',
    })
  }

  const clusters = [...byId.values()]
  for (const cluster of clusters) {
    cluster.tasks = [...new Set(cluster.runs.map((r) => r.task_id))].sort()
    cluster.agents = [...new Set(cluster.runs.map((r) => r.agent))].sort()
    const seqs = new Set(
      cluster.runs.map((r) => r.failure_step?.seq).filter((s): s is number => typeof s === 'number'),
    )
    // Only when every attributed run agrees. Showing one run's seq as the
    // cluster's would be a guess dressed up as a fact.
    cluster.representativeSeq = seqs.size === 1 ? [...seqs][0] : null
  }

  return clusters.sort(
    (a, b) => b.runs.length - a.runs.length || b.tasks.length - a.tasks.length || a.id.localeCompare(b.id),
  )
}

/** A run's deep link into its own trace, opened at the attributed step. */
export function stepLink(row: ResultRow): string {
  const seq = row.failure_step?.seq
  const base = `/results/${encodeURIComponent(row.bundle)}`
  return typeof seq === 'number' ? `${base}?seq=${seq}` : base
}
