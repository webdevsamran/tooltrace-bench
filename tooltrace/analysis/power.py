"""How many runs a question needs, and what the runs you did can answer.

Every number this project produces carries a confidence interval, and the
interval is always computed *after* the runs. That leaves the most consequential
decision unsupported: how many runs to do. People pick 3, or 10, because those
are round numbers, and then read a difference the sample cannot support — which
is the failure the whole `showdown`/`pr-report` line of work exists to prevent,
addressed one step too late.

This module answers the question before the spend:

- `minimum_detectable_effect(n)` — with this many runs per arm, the smallest
  difference that would clear the noise.
- `runs_for_effect(delta)` — to detect a difference this size, this many runs.
- `power_report()` — both, plus the honest sentence about what a planned sweep
  can and cannot conclude.

And afterwards, `variance_decomposition` answers a question nobody could ask:
when a rate wobbles, is that the agent or the harness? The distinction matters
because they have different fixes. A harness that contributes most of the
variance is a harness that needs pinning down, and no amount of re-running the
agent will help.

Everything is normal-approximation on proportions, computed in closed form. No
dependency, and no simulation, so two runs of the same planning question give the
same answer — a planner that returned a different number each time would be
worse than no planner.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from statistics import fmean, pvariance
from typing import Any

#: Two-sided 95% and 80% power. Stated as constants rather than buried in a
#: formula, because these are conventions and a reader is entitled to disagree
#: with them.
Z_ALPHA = 1.959964
Z_POWER = 0.841621

#: Below this, the normal approximation to a binomial is not trustworthy and the
#: numbers this module produces are decoration.
MIN_TRUSTWORTHY_N = 10


def minimum_detectable_effect(
    n_per_arm: int,
    *,
    baseline_rate: float = 0.5,
    z_alpha: float = Z_ALPHA,
    z_power: float = Z_POWER,
) -> float | None:
    """The smallest difference in success rate that `n_per_arm` runs can detect.

    `baseline_rate` matters and defaults to the worst case. Variance in a
    proportion peaks at 0.5, so 0.5 gives the most conservative — largest —
    minimum detectable effect. A planner that assumed a 0.95 baseline would
    promise more sensitivity than a sweep will deliver.

    Returns None below `MIN_TRUSTWORTHY_N`: a normal approximation on four runs
    produces a number, and the number is not information.
    """
    if n_per_arm < MIN_TRUSTWORTHY_N:
        return None
    p = min(max(baseline_rate, 0.0), 1.0)
    variance = p * (1 - p)
    if variance <= 0:
        # A baseline of exactly 0 or 1 has no variance under this approximation,
        # which would imply infinite sensitivity. It does not; the approximation
        # simply does not apply there.
        return None
    effect = (z_alpha + z_power) * math.sqrt(2 * variance / n_per_arm)
    return round(min(effect, 1.0), 6)


def runs_for_effect(
    delta: float, *, baseline_rate: float = 0.5, z_alpha: float = Z_ALPHA, z_power: float = Z_POWER
) -> int | None:
    """Runs per arm needed to detect a difference of `delta`.

    The inverse of the above. Returns None for a non-positive delta: "how many
    runs to detect no difference" has no answer, and returning a large number
    would imply one exists.
    """
    if delta <= 0:
        return None
    p = min(max(baseline_rate, 0.0), 1.0)
    variance = p * (1 - p)
    if variance <= 0:
        return None
    n = 2 * variance * ((z_alpha + z_power) / delta) ** 2
    return max(MIN_TRUSTWORTHY_N, math.ceil(n))


def power_report(
    n_per_arm: int,
    *,
    baseline_rate: float = 0.5,
    interesting_effects: Sequence[float] = (0.05, 0.10, 0.20),
) -> dict[str, Any]:
    """What a planned sweep of `n_per_arm` runs can and cannot conclude."""
    mde = minimum_detectable_effect(n_per_arm, baseline_rate=baseline_rate)
    plan = {
        f"{effect:.2f}": runs_for_effect(effect, baseline_rate=baseline_rate)
        for effect in interesting_effects
    }
    if mde is None:
        statement = (
            f"{n_per_arm} runs per arm is below {MIN_TRUSTWORTHY_N}, where the normal "
            "approximation stops being trustworthy. This sweep can demonstrate that "
            "something runs; it cannot compare two agents."
        )
    else:
        statement = (
            f"With {n_per_arm} runs per arm, a difference smaller than "
            f"{mde * 100:.1f} percentage points will not be distinguishable from noise. "
            "A smaller measured difference is not evidence of no difference."
        )
    return {
        "runs_per_arm": n_per_arm,
        "baseline_rate": baseline_rate,
        "minimum_detectable_effect": mde,
        "runs_needed_for": plan,
        "alpha": 0.05,
        "power": 0.80,
        "statement": statement,
        # The assumption most likely to be wrong, stated where it will be read.
        "assumption": (
            "Two-sided test on independent runs, normal approximation to the binomial. "
            "Runs that share a cache, a seed or a machine are not independent and this "
            "understates the runs required."
        ),
    }


def variance_decomposition(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Split observed variance into within-configuration and between-task parts.

    A success rate that moves between sweeps has two possible sources, and they
    have different fixes. Repeating the *same* agent on the *same* task and
    getting different answers is nondeterminism — the model's, or the harness's.
    Getting different answers across *different* tasks is the benchmark doing its
    job, and is not instability at all.

    Reporting a single standard deviation conflates them, which is how a stable
    agent on a diverse task set gets described as flaky.

    The honest limit, stated in the output: this cannot separate the *model's*
    nondeterminism from the *harness's*. Both live inside the within-configuration
    term. Separating them needs a fixed-seed control arm, which
    `docs/statistics.md` describes and no adapter currently guarantees.
    """
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for run in runs:
        key = (str(run.get("agent", "")), str(run.get("task_id", "")))
        groups[key].append(1.0 if run.get("success") else 0.0)

    repeated = {k: v for k, v in groups.items() if len(v) > 1}
    if not repeated:
        return {
            "measurable": False,
            "reason": (
                "no agent/task pair was run more than once, so within-configuration "
                "variance cannot be observed at all"
            ),
            "configurations": len(groups),
            "runs": len(runs),
        }

    # Within: mean of the per-configuration variances, weighted by group size.
    within_terms = [(len(v), pvariance(v)) for v in repeated.values()]
    total_weight = sum(w for w, _ in within_terms)
    within = sum(w * var for w, var in within_terms) / total_weight

    # Between: variance of the per-configuration means.
    group_means = [fmean(v) for v in groups.values()]
    between = pvariance(group_means) if len(group_means) > 1 else 0.0

    total = within + between
    return {
        "measurable": True,
        "runs": len(runs),
        "configurations": len(groups),
        "repeated_configurations": len(repeated),
        "within_configuration_variance": round(within, 6),
        "between_task_variance": round(between, 6),
        # None rather than 0 when there is no variance at all: "0% of the
        # variance is nondeterminism" and "there was no variance" are different
        # statements and only one of them is interesting.
        "nondeterminism_share": round(within / total, 6) if total > 0 else None,
        "note": (
            "Within-configuration variance covers the model's nondeterminism and the "
            "harness's together; this cannot separate them without a fixed-seed control "
            "arm. Between-task variance is the benchmark working, not instability."
        ),
    }


def _beta_binomial_probability(
    a1: float, b1: float, a2: float, b2: float, *, grid: int = 2000
) -> float:
    """P(theta_1 > theta_2) for two Beta posteriors, by numerical integration.

    A closed form exists for integer parameters and overflows for the counts a
    real sweep produces. A fixed grid is deterministic, has no dependency, and is
    accurate to well within the precision anybody should read off this number.
    """
    from math import lgamma

    def log_beta_pdf(x: float, a: float, b: float) -> float:
        if x <= 0 or x >= 1:
            return float("-inf")
        return (
            (a - 1) * math.log(x)
            + (b - 1) * math.log(1 - x)
            + lgamma(a + b)
            - lgamma(a)
            - lgamma(b)
        )

    step = 1.0 / grid
    # P(t1 > t2) = sum over t1 of pdf1(t1) * CDF2(t1)
    cdf2 = 0.0
    total = 0.0
    for i in range(grid):
        x = (i + 0.5) * step
        pdf2 = math.exp(log_beta_pdf(x, a2, b2))
        pdf1 = math.exp(log_beta_pdf(x, a1, b1))
        total += pdf1 * (cdf2 + 0.5 * pdf2 * step) * step
        cdf2 += pdf2 * step
    return min(max(total, 0.0), 1.0)


def bayesian_comparison(
    successes_a: int,
    total_a: int,
    successes_b: int,
    total_b: int,
    *,
    label_a: str = "A",
    label_b: str = "B",
    prior_alpha: float = 1.0,
    prior_beta: float = 1.0,
) -> dict[str, Any]:
    """P(A is better than B), with a uniform prior by default.

    This answers a question a confidence interval does not: "how likely is it
    that A is actually better", which is what people read a frequentist p-value
    as meaning anyway. Reporting it directly is more honest than letting the
    misreading do the work.

    The uniform Beta(1,1) prior is the default and is stated in the output. A
    prior chosen after seeing the data is how a Bayesian analysis becomes a way
    to get the answer you wanted, so it is an explicit argument, never inferred.
    """
    if total_a <= 0 or total_b <= 0:
        return {
            "measurable": False,
            "reason": "both arms need at least one run",
        }

    a1, b1 = prior_alpha + successes_a, prior_beta + (total_a - successes_a)
    a2, b2 = prior_alpha + successes_b, prior_beta + (total_b - successes_b)
    probability = _beta_binomial_probability(a1, b1, a2, b2)

    mean_a = a1 / (a1 + b1)
    mean_b = a2 / (a2 + b2)
    return {
        "measurable": True,
        "labels": [label_a, label_b],
        # A list, not a dict keyed by label. Comparing an agent with itself is a
        # deliberate sanity check in `showdown`, and a label-keyed dict silently
        # collapses the two arms into one -- losing exactly the arm the check
        # exists to compare.
        "posterior_mean": [
            {"label": label_a, "mean": round(mean_a, 6)},
            {"label": label_b, "mean": round(mean_b, 6)},
        ],
        "probability_a_better": round(probability, 6),
        "probability_b_better": round(1 - probability, 6),
        "prior": f"Beta({prior_alpha}, {prior_beta})",
        # A probability near 0.5 is not a tie -- it is an absence of evidence in
        # either direction, and on small samples that is what it almost always is.
        "reading": _bayes_reading(probability, min(total_a, total_b), label_a, label_b),
    }


def _bayes_reading(probability: float, smallest_arm: int, label_a: str, label_b: str) -> str:
    if smallest_arm < MIN_TRUSTWORTHY_N:
        return (
            f"the smaller arm has {smallest_arm} runs; this posterior is dominated by the "
            "prior and should not be quoted"
        )
    if probability >= 0.95:
        return f"{label_a} is better with probability {probability:.2f}"
    if probability <= 0.05:
        return f"{label_b} is better with probability {1 - probability:.2f}"
    return (
        f"no clear winner: P({label_a} better) = {probability:.2f}. That is an absence of "
        "evidence, not evidence the two are equal"
    )
