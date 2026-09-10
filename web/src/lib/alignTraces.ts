import type { TraceLine } from '../components'

/**
 * Align two traces so the same decision sits on the same row.
 *
 * Two runs of the same task rarely have the same number of steps, and a
 * side-by-side view that just puts row 1 next to row 1 goes out of register at
 * the first extra call — after which every remaining row is comparing unrelated
 * things while looking like a comparison. That is worse than no comparison,
 * because it produces confident wrong readings.
 *
 * So this is a diff rather than a zip. It is the standard longest-common-
 * subsequence alignment over a *signature* per step, which yields three kinds of
 * row: both sides did the same thing, only the left did, only the right did.
 *
 * The signature is what decides what "the same thing" means, and it is
 * deliberately the tool plus its primary argument rather than the whole
 * argument set. Two `write_file` calls to the same path with different content
 * are the same *decision* taken differently, and that is exactly the row a
 * reader wants aligned so they can see the content differ. Including the
 * content would push them apart into two unrelated rows and hide it.
 */

export type Side = 'both' | 'left' | 'right'

export interface AlignedRow {
  side: Side
  left: TraceLine | null
  right: TraceLine | null
}

/** What makes two steps "the same decision". */
export function signature(event: TraceLine): string {
  const tool = event.tool ?? event.type
  // The first path-like or short token in the summary stands in for the
  // primary argument, which the trace index does not carry separately.
  const argument = (event.summary ?? '').split(/\s+/).find((token) => token.includes('.')) ?? ''
  return `${event.type}:${tool}:${argument}`
}

/** Only the steps worth comparing: a decision, not a heartbeat. */
export function comparableSteps(events: TraceLine[]): TraceLine[] {
  return events.filter((e) => e.type === 'tool_request' || e.type === 'agent_action')
}

export function alignTraces(left: TraceLine[], right: TraceLine[]): AlignedRow[] {
  const a = comparableSteps(left)
  const b = comparableSteps(right)
  const sa = a.map(signature)
  const sb = b.map(signature)

  // Longest common subsequence table. Both traces are short — a run is tens of
  // steps, not thousands — so the quadratic table is far cheaper than the
  // dependency an off-the-shelf differ would add to a repo that deliberately
  // has none.
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () =>
    new Array<number>(b.length + 1).fill(0),
  )
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = sa[i] === sb[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const rows: AlignedRow[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (sa[i] === sb[j]) {
      rows.push({ side: 'both', left: a[i], right: b[j] })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      rows.push({ side: 'left', left: a[i], right: null })
      i++
    } else {
      rows.push({ side: 'right', left: null, right: b[j] })
      j++
    }
  }
  while (i < a.length) rows.push({ side: 'left', left: a[i++], right: null })
  while (j < b.length) rows.push({ side: 'right', left: null, right: b[j++] })
  return rows
}

export interface AlignmentSummary {
  shared: number
  onlyLeft: number
  onlyRight: number
  divergedAt: number | null
  statement: string
}

export function summarise(rows: AlignedRow[]): AlignmentSummary {
  const shared = rows.filter((r) => r.side === 'both').length
  const onlyLeft = rows.filter((r) => r.side === 'left').length
  const onlyRight = rows.filter((r) => r.side === 'right').length
  // The index of the first row the two runs did not share. This is the single
  // most useful number in the view: everything before it is common ground, and
  // everything worth reading starts here.
  const divergedIndex = rows.findIndex((r) => r.side !== 'both')
  const divergedAt = divergedIndex === -1 ? null : divergedIndex

  return {
    shared,
    onlyLeft,
    onlyRight,
    divergedAt,
    statement:
      divergedAt === null
        ? `Both runs took the same ${shared} step(s). Any difference in outcome came from the results, not the decisions.`
        : `The runs agree for ${divergedAt} step(s), then diverge: ${onlyLeft} step(s) only on the left, ${onlyRight} only on the right.`,
  }
}
