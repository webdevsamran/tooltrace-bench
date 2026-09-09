"""Reliability statistics over repeated runs.

All functions are pure and deterministic given their inputs.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from itertools import pairwise


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile (p in [0, 100])."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    frac = rank - lower
    return ordered[lower] * (1 - frac) + ordered[upper] * frac


def p50(values: Sequence[float]) -> float:
    return percentile(values, 50)


def p95(values: Sequence[float]) -> float:
    return percentile(values, 95)


def success_rate(successes: Sequence[bool]) -> float:
    return sum(1 for s in successes if s) / len(successes) if successes else 0.0


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if total == 0:
        return (0.0, 0.0)
    phat = successes / total
    denom = 1 + z * z / total
    center = (phat + z * z / (2 * total)) / denom
    spread = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denom
    return (max(0.0, center - spread), min(1.0, center + spread))


def consistency(successes: Sequence[bool]) -> dict[str, float]:
    """Success rate with a Wilson 95% confidence interval."""
    n = len(successes)
    k = sum(1 for s in successes if s)
    low, high = wilson_interval(k, n)
    return {"rate": success_rate(successes), "ci_low": low, "ci_high": high, "n": n}


def recovery_rate(recovery_opportunities: int, recoveries: int) -> float | None:
    """Fraction of injected faults after which the agent still completed."""
    if recovery_opportunities <= 0:
        return None
    return recoveries / recovery_opportunities


def summarize_reliability(
    results: list[dict[str, object]],
    *,
    ci_method: str = "wilson",
) -> dict[str, object]:
    """Aggregate reliability metrics from per-run result dicts.

    Expected keys per result: success (bool), partial_success (bool), steps,
    tool_calls, failed_tool_calls, wall_ms, recovered (bool|None).

    ``ci_method`` selects the interval for the *success rate*:

    - ``"wilson"`` (default, unchanged): the right choice for a proportion,
      and well behaved at the extremes where a normal approximation is not.
    - ``"percentile"`` / ``"bca"``: bootstrap. Use these when you want the same
      estimator applied to the success rate as to the non-binary metrics, or
      when the runs are known not to be independent Bernoulli draws.

    Regardless of the method, a `flakiness` block reports a Wald-Wolfowitz
    runs test. Every interval here assumes independent runs; that block is
    what tells you whether the assumption held. A 60% rate from unpredictable
    failures and a 60% rate from a reliably-failing subset are different
    findings, and the rate alone cannot separate them.

    Bootstrap intervals for `steps` and `wall_ms` are always included when
    there are at least two runs: Wilson does not apply to them at all, so
    before this they had no interval of any kind.
    """
    if not results:
        return {}
    successes = [bool(r.get("success")) for r in results]
    partials = [bool(r.get("partial_success")) for r in results]

    def _nums(key: str) -> list[float]:
        return [float(v) for r in results if isinstance((v := r.get(key)), (int, float))]

    steps = _nums("steps")
    tool_calls = _nums("tool_calls")
    failed_calls = _nums("failed_tool_calls")
    wall = _nums("wall_ms")
    opportunities = sum(1 for r in results if r.get("recovered") is not None)
    recoveries = sum(1 for r in results if r.get("recovered"))
    if ci_method == "wilson":
        rate_block = consistency(successes)
    elif ci_method in ("percentile", "bca"):
        as_floats = [1.0 if s else 0.0 for s in successes]
        interval = bootstrap_interval(as_floats, method=ci_method)
        rate_block = {
            "rate": success_rate(successes),
            "ci_low": round(interval[0], 6) if interval else 0.0,
            "ci_high": round(interval[1], 6) if interval else 0.0,
            "n": len(successes),
        }
    else:
        raise ValueError(f"unknown ci_method {ci_method!r}; use wilson, percentile or bca")

    out: dict[str, object] = {
        "runs": len(results),
        "ci_method": ci_method,
        **rate_block,
        "partial_success_rate": success_rate(partials),
        "steps_mean": round(mean(steps), 3),
        "steps_p95": round(p95(steps), 3),
        "tool_calls_mean": round(mean(tool_calls), 3),
        "failed_tool_calls_mean": round(mean(failed_calls), 3),
        "wall_ms_p50": round(p50(wall), 3),
        "wall_ms_p95": round(p95(wall), 3),
    }
    # Non-binary metrics get a bootstrap interval or nothing -- never a
    # Wilson interval, which is defined for proportions only.
    for key, sample in (("steps", steps), ("wall_ms", wall)):
        interval = bootstrap_interval(sample)
        if interval is not None:
            out[f"{key}_ci95"] = [round(interval[0], 3), round(interval[1], 3)]

    out["flakiness"] = runs_test(successes)

    # Where the wall time actually went. `model_ms` and `tool_ms` were on every
    # result and never reported together, so nobody could tell a slow-thinking
    # agent from a slow-acting one -- the first question anyone optimising an
    # agent has. An adapter that cannot report model time leaves the split
    # unknown rather than attributing the remainder to tools.
    from tooltrace.telemetry.hardware import aggregate_latency

    out["latency"] = aggregate_latency(results)

    rec = recovery_rate(opportunities, recoveries)
    if rec is not None:
        out["recovery_rate"] = round(rec, 4)
    return out


# ---------------------------------------------------------------------------
# Bootstrap intervals for non-binary metrics
#
# Wilson is for proportions. Applying it to steps or latency is a category
# error, and normal-approximation intervals assume a symmetry that latency
# distributions do not have -- they are right-skewed, so a symmetric interval
# understates the upper tail exactly where it matters. Bootstrapping resamples
# the observed data instead of assuming a shape.
# ---------------------------------------------------------------------------


def _arithmetic_mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _resample_indices(n: int, rounds: int, seed: int) -> list[list[int]]:
    """Deterministic resample indices.

    Seeded explicitly rather than using the global RNG: a benchmark that
    reports a different confidence interval each time it is run on identical
    data is not reproducible, which is the property this project sells.
    """
    rng = random.Random(seed)
    return [[rng.randrange(n) for _ in range(n)] for _ in range(rounds)]


def bootstrap_interval(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] | None = None,
    *,
    confidence: float = 0.95,
    rounds: int = 2000,
    seed: int = 20260907,
    method: str = "percentile",
) -> tuple[float, float] | None:
    """Bootstrap confidence interval for any statistic of a sample.

    ``method`` is ``"percentile"`` (simple, unbiased for symmetric statistics)
    or ``"bca"`` (bias-corrected and accelerated, better for skewed data and
    small samples, at the cost of one jackknife pass).

    Returns ``None`` for fewer than two observations: an interval from a
    single point would be a fabricated number, and this project reports
    unmeasurable quantities as missing rather than guessing them.
    """
    stat = statistic if statistic is not None else _arithmetic_mean
    n = len(values)
    if n < 2:
        return None
    observed = stat(values)
    samples = sorted(stat([values[i] for i in idx]) for idx in _resample_indices(n, rounds, seed))
    alpha = 1.0 - confidence

    if method == "percentile":
        lo_q, hi_q = alpha / 2, 1 - alpha / 2
    elif method == "bca":
        # Bias correction: how far the bootstrap distribution sits from the
        # observed statistic.
        below = sum(1 for s in samples if s < observed)
        if below in (0, len(samples)):
            # Degenerate -- every resample landed on one side. Fall back rather
            # than divide by an infinite z0.
            lo_q, hi_q = alpha / 2, 1 - alpha / 2
        else:
            z0 = _norm_ppf(below / len(samples))
            # Acceleration from the jackknife's third moment.
            jack = [stat([v for j, v in enumerate(values) if j != i]) for i in range(n)]
            jack_mean = sum(jack) / n
            num = sum((jack_mean - x) ** 3 for x in jack)
            den = 6.0 * (sum((jack_mean - x) ** 2 for x in jack) ** 1.5)
            a = num / den if den else 0.0
            z_lo, z_hi = _norm_ppf(alpha / 2), _norm_ppf(1 - alpha / 2)
            lo_q = _norm_cdf(z0 + (z0 + z_lo) / (1 - a * (z0 + z_lo)))
            hi_q = _norm_cdf(z0 + (z0 + z_hi) / (1 - a * (z0 + z_hi)))
    else:
        raise ValueError(f"unknown bootstrap method {method!r}; use percentile or bca")

    lo = samples[max(0, min(len(samples) - 1, int(lo_q * len(samples))))]
    hi = samples[max(0, min(len(samples) - 1, int(hi_q * len(samples))))]
    return (min(lo, hi), max(lo, hi))


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse normal CDF by bisection.

    Deliberately dependency-free: pulling in scipy for one quantile would be a
    large dependency for a package whose runtime set is six.
    """
    if not 0.0 < p < 1.0:
        return -8.0 if p <= 0.0 else 8.0
    lo, hi = -8.0, 8.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _norm_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Flakiness
# ---------------------------------------------------------------------------


def runs_test(successes: Sequence[bool]) -> dict[str, object]:
    """Wald-Wolfowitz runs test on a pass/fail sequence.

    A 60% success rate can mean two very different things: an agent that fails
    unpredictably, or one that reliably fails a subset of attempts. The rate
    alone cannot tell them apart. This counts *runs* -- maximal blocks of
    consecutive identical outcomes -- and compares that against how many an
    independent sequence with the same totals would produce.

    Too few runs means the outcomes clump (a systematic change mid-sequence,
    such as a cache warming or a resource leak). Too many means they alternate
    more than chance allows. Both indicate the runs are not independent draws,
    which is the assumption every interval here rests on.

    ``z`` is None when the test does not apply (fewer than two of either
    outcome); reporting a number there would be fabricating one.
    """
    n = len(successes)
    n1 = sum(1 for s in successes if s)
    n2 = n - n1
    observed_runs = 1 + sum(1 for a, b in pairwise(successes) if a != b) if n else 0

    if n1 < 2 or n2 < 2:
        return {
            "runs": observed_runs,
            "expected_runs": None,
            "z": None,
            "flaky": False,
            "reason": "not enough of both outcomes to test independence",
        }

    expected = (2.0 * n1 * n2) / n + 1.0
    variance = (2.0 * n1 * n2 * (2.0 * n1 * n2 - n)) / (n * n * (n - 1.0))
    if variance <= 0:
        return {
            "runs": observed_runs,
            "expected_runs": round(expected, 3),
            "z": None,
            "flaky": False,
            "reason": "zero variance",
        }
    z = (observed_runs - expected) / math.sqrt(variance)
    flaky = abs(z) > 1.96
    if not flaky:
        reason = "pass/fail pattern is consistent with independent runs"
    elif z > 0:
        reason = "outcomes alternate more than chance allows; results are unstable"
    else:
        reason = "outcomes clump; something changed part-way through the sequence"
    return {
        "runs": observed_runs,
        "expected_runs": round(expected, 3),
        "z": round(z, 3),
        "flaky": flaky,
        "reason": reason,
    }
