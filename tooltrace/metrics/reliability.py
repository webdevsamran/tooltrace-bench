"""Reliability statistics: pass@k, pass^k with correct denominators, bootstrap
confidence intervals and paired-run deltas (features 31, 72, 73, 74).

Definitions (Chen et al. 2021 for pass@k):
    pass@k = 1 - C(n-c, k) / C(n, k)

pass^k (reliability): fraction of tasks where ALL k runs passed.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence


def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k given n total samples with c correct ones."""
    if n <= 0 or k <= 0:
        return 0.0
    if k > n:
        k = n
    return 1.0 - (math.comb(n - c, k) / math.comb(n, k))


def aggregate_pass_at_k(results_by_task: dict[str, Sequence[bool]], k: int) -> float:
    """Mean unbiased pass@k across tasks."""
    if not results_by_task:
        return 0.0
    vals = [pass_at_k(len(v), sum(1 for s in v if s), k) for v in results_by_task.values()]
    return sum(vals) / len(vals)


def pass_hat_k(results_by_task: dict[str, Sequence[bool]], k: int) -> float:
    """pass^k: fraction of tasks that passed on ALL of their first k runs.

    Tasks with fewer than k runs are excluded from the denominator (correct
    denominator rule); if no task qualifies the result is 0.0.
    """
    eligible = [v[:k] for v in results_by_task.values() if len(v) >= k]
    if not eligible:
        return 0.0
    return sum(1 for v in eligible if all(v)) / len(eligible)


def bootstrap_ci(
    values: Sequence[float],
    statistic: str = "mean",
    iterations: int = 2000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float, float]:
    """Deterministic seeded bootstrap CI. Offline, dependency-free."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    data = list(values)
    n = len(data)

    def stat(sample: list[float]) -> float:
        if statistic == "mean":
            return sum(sample) / len(sample)
        return sorted(sample)[len(sample) // 2]

    stats = sorted(stat([data[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations))
    alpha = (1.0 - confidence) / 2.0
    lo_idx = max(0, int(alpha * iterations))
    hi_idx = min(iterations - 1, int((1 - alpha) * iterations))
    return (stats[lo_idx], stats[hi_idx])


def paired_delta(a: Sequence[bool], b: Sequence[bool]) -> dict[str, float | None]:
    """Paired-run analysis when both candidates ran identical task seeds."""
    if len(a) != len(b) or not a:
        return {"wins": None, "losses": None, "ties": None, "discordant_rate": None}
    wins = sum(1 for x, y in zip(a, b, strict=True) if x and not y)
    losses = sum(1 for x, y in zip(a, b, strict=True) if y and not x)
    ties = len(a) - wins - losses
    discordant = wins + losses
    rate = (abs(wins - losses) / discordant) if discordant else 0.0
    return {
        "wins": float(wins),
        "losses": float(losses),
        "ties": float(ties),
        "discordant_rate": round(rate, 4),
    }


def effect_size_cohens_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for two proportions."""

    def phi(p: float) -> float:
        p = min(max(p, 1e-9), 1 - 1e-9)
        return 2 * math.asin(math.sqrt(p))

    return round(phi(p1) - phi(p2), 4)


def significance_note(n_a: int, n_b: int, min_sample: int = 30) -> str:
    """Avoid automatic winner claims from tiny samples (feature 73)."""
    if n_a < min_sample or n_b < min_sample:
        return (
            f"sample sizes ({n_a}, {n_b}) below {min_sample}; "
            "differences are reported but no winner is claimed"
        )
    return "sample sizes sufficient for directional comparison"
