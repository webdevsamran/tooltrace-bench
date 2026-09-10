import { describe, expect, it } from 'vitest'
import type { TraceLine } from '../components'
import { alignTraces, summarise } from '../lib/alignTraces'
import FIXTURE from '../../../tests/fixtures/trace_alignment.json'

/**
 * The cross-language contract.
 *
 * Two implementations of this alignment ship here: Python for `tooltrace
 * shadow`, TypeScript for the dashboard's run diff. They cannot be one -- the
 * dashboard aligns two runs a user picked, in the browser, with no server -- so
 * the risk is that they drift into disagreeing about what "the same decision"
 * means, and a reader comparing the same two runs in the CLI and in the
 * dashboard gets two different answers about where they diverged.
 *
 * `tests/fixtures/trace_alignment.json` is read by both suites. A case added
 * there has to pass in both.
 */

function steps(pairs: string[][]): TraceLine[] {
  return pairs.map(([tool, resource], index) => ({
    seq: index,
    type: 'tool_request',
    tool,
    // The signature takes the first dotted token from the summary, so the
    // resource is written in a form both sides read the same way.
    summary: resource.includes('.') ? resource : `${resource}.x`,
  }))
}

describe('the alignment contract shared with the Python implementation', () => {
  for (const testCase of FIXTURE.cases) {
    it(testCase.name, () => {
      const rows = alignTraces(steps(testCase.left), steps(testCase.right))
      expect(rows.map((row) => row.side)).toEqual(testCase.sides)
      expect(summarise(rows).divergedAt).toEqual(testCase.diverged_at)
    })
  }

  it('covers more than a couple of cases, or it is not a contract', () => {
    expect(FIXTURE.cases.length).toBeGreaterThanOrEqual(8)
  })
})
