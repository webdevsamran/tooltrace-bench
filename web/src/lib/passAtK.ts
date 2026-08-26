/** Unbiased pass@k estimator over recorded binary outcomes:
 * pass@k = E[1 − C(n−c, k)/C(n, k)] with n attempts and c successes.
 * Small samples produce wide uncertainty — treat as indicative only. */
export function estimatePassAtK(outcomes: number[], maxK = 10): { x: number; y: number }[] {
  const n = outcomes.length
  const c = outcomes.reduce((a, b) => a + b, 0)
  const ks = Array.from({ length: Math.min(maxK, n) }, (_, i) => i + 1)
  return ks.map((k) => {
    let probAllFailWithinK = 1
    for (let i = 0; i < k; i++) probAllFailWithinK *= (n - c - i) / (n - i)
    return { x: k, y: 1 - probAllFailWithinK }
  })
}
