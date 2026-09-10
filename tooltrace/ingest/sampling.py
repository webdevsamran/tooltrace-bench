"""Which production traces to keep when you cannot score all of them.

At a few thousand traces a day, scoring everything is not a budget decision that
gets made once -- it is a bill that arrives every day. So something has to choose,
and the choice is where most of the damage in a production evaluation pipeline
gets done.

## Uniform random sampling is the wrong default, and it is the usual one

The thing worth finding is failure, and failure is rare. Sample 1% of traffic
uniformly and you see 1% of the failures: a class that happens twice a week
becomes a class you see roughly once a year. Every review meeting then looks at
a sample in which everything worked, which is precisely the sample that teaches
nothing.

So the default here is **stratified**: keep every trace that already looks
wrong, keep a bounded share of the rest, and -- this is the part usually left
out -- **record the rate each stratum was kept at**, because the sample is now
biased on purpose and any rate computed from it is wrong unless the bias is
undone.

## The correction is the feature

A stratified sample where errored traces are kept at 100% and clean ones at 1%
will show a failure rate near 50%, which is not the failure rate. `estimate_rate`
inverts the sampling weights and produces the population figure, along with how
many traces each estimate rests on. A pipeline that stratifies and then reports
the raw sample rate is reporting a number about its own sampling policy.

Selection is deterministic given a seed: the same traces are chosen on a re-run,
which is what makes a sampled evaluation reproducible at all.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

UNIFORM = "uniform"
STRATIFIED = "stratified"
ALL = "all"

POLICIES = (STRATIFIED, UNIFORM, ALL)

#: Strata, most interesting first. The first matching stratum wins, so order is
#: meaningful: an errored *and* long trace is kept as an error.
ERRORED = "errored"
LONG = "long"
CLEAN = "clean"

#: A trace this long is worth a look whatever its outcome: an agent that took
#: forty steps to succeed has a problem the success rate cannot see.
LONG_TRACE_STEPS = 25


@dataclass(frozen=True)
class Stratum:
    name: str
    #: Share of this stratum to keep, 0..1.
    rate: float
    why: str


DEFAULT_STRATA: tuple[Stratum, ...] = (
    Stratum(
        ERRORED,
        1.0,
        "Everything that already looks wrong. This is what the pipeline exists to find, "
        "and it is rare enough that sampling it at all loses most of it",
    ),
    Stratum(
        LONG,
        0.25,
        f"More than {LONG_TRACE_STEPS} steps. An agent that took forty steps to succeed has "
        "a problem the success rate cannot see",
    ),
    Stratum(
        CLEAN,
        0.01,
        "Short and successful. Kept at a low rate for a baseline, not for discovery: a "
        "sample of these teaches nothing except that things mostly work",
    ),
)


def classify(trace: dict[str, Any]) -> str:
    """Which stratum a trace belongs to. First match wins."""
    if trace.get("error") or trace.get("failed") or trace.get("status") == "error":
        return ERRORED
    steps = trace.get("steps")
    if isinstance(steps, int | float) and steps > LONG_TRACE_STEPS:
        return LONG
    return CLEAN


def _keep_fraction(trace_id: str, seed: int) -> float:
    """A stable number in [0, 1) for this trace.

    Hashed rather than drawn from a random number generator, so the decision
    depends only on the trace id and the seed. A sequence-dependent draw would
    make the sample depend on the order traces arrived in, and a re-run that
    processed them in a different order would keep a different set -- which
    would quietly make a sampled evaluation unreproducible.
    """
    digest = hashlib.sha256(f"{seed}:{trace_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def sample(
    traces: list[dict[str, Any]],
    *,
    policy: str = STRATIFIED,
    rate: float = 0.01,
    seed: int = 0,
    strata: tuple[Stratum, ...] = DEFAULT_STRATA,
) -> dict[str, Any]:
    """Choose which traces to score, and record what was chosen at what rate."""
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; expected one of {', '.join(POLICIES)}")

    by_stratum = {s.name: s for s in strata}
    kept: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    kept_counts: dict[str, int] = {}

    for trace in traces:
        name = classify(trace)
        seen[name] = seen.get(name, 0) + 1
        trace_id = str(trace.get("trace_id") or trace.get("id") or "")
        if policy == ALL:
            threshold = 1.0
        elif policy == UNIFORM:
            threshold = rate
        else:
            stratum = by_stratum.get(name)
            threshold = stratum.rate if stratum else rate

        if not trace_id:
            # No id, no stable decision. Kept rather than dropped: losing a
            # trace because it was missing a field would bias the sample in a
            # direction nobody chose.
            kept.append(trace)
            kept_counts[name] = kept_counts.get(name, 0) + 1
            continue
        if _keep_fraction(trace_id, seed) < threshold:
            kept.append(trace)
            kept_counts[name] = kept_counts.get(name, 0) + 1

    # The realised rate per stratum, not the requested one. With small
    # populations they differ, and the correction has to use what actually
    # happened rather than what was asked for.
    realised = {
        name: (kept_counts.get(name, 0) / count if count else 0.0) for name, count in seen.items()
    }

    return {
        "policy": policy,
        "seed": seed,
        "population": len(traces),
        "kept": len(kept),
        "traces": kept,
        "seen_by_stratum": seen,
        "kept_by_stratum": kept_counts,
        "realised_rate": {k: round(v, 6) for k, v in realised.items()},
        "strata": [{"name": s.name, "rate": s.rate, "why": s.why} for s in strata],
        "is_biased": policy == STRATIFIED,
        "statement": _statement(policy, len(traces), len(kept), realised),
    }


def _statement(policy: str, population: int, kept: int, realised: dict[str, float]) -> str:
    if policy == ALL:
        return f"every one of {population} trace(s) kept; nothing to correct for."
    if policy == UNIFORM:
        return (
            f"{kept} of {population} trace(s) kept uniformly. Unbiased, and it finds failures "
            "at the rate they occur -- which for a rare class means almost never."
        )
    rates = ", ".join(f"{name} at {rate:.0%}" for name, rate in sorted(realised.items()))
    return (
        f"{kept} of {population} trace(s) kept, stratified ({rates}). **This sample is biased "
        "on purpose**: any rate computed directly from it is a statement about the sampling "
        "policy. Use `estimate_rate` to recover the population figure."
    )


def estimate_rate(sampled: dict[str, Any], scored: list[dict[str, Any]]) -> dict[str, Any]:
    """The population failure rate, correcting for how each stratum was sampled.

    A stratified sample that keeps every error and 1% of clean traces will show
    a failure rate near 50%. That is not the failure rate; it is a property of
    the policy. Inverting the sampling weights recovers the population figure.

    Reported with the count each stratum's estimate rests on, because a stratum
    sampled down to three traces contributes an estimate with an interval wide
    enough to swallow the answer.
    """
    realised = sampled.get("realised_rate") or {}
    seen = sampled.get("seen_by_stratum") or {}

    failures_by_stratum: dict[str, int] = {}
    counts_by_stratum: dict[str, int] = {}
    for trace in scored:
        name = classify(trace)
        counts_by_stratum[name] = counts_by_stratum.get(name, 0) + 1
        if not trace.get("success", True):
            failures_by_stratum[name] = failures_by_stratum.get(name, 0) + 1

    if not counts_by_stratum:
        return {
            "measurable": False,
            "reason": "no scored traces, so there is nothing to project onto the population",
        }

    estimated_failures = 0.0
    contributions: list[dict[str, Any]] = []
    thin: list[str] = []
    for name, count in counts_by_stratum.items():
        rate = realised.get(name) or 0.0
        failures = failures_by_stratum.get(name, 0)
        # Each kept trace stands for 1/rate traces in the population.
        weight = (1.0 / rate) if rate > 0 else 0.0
        contribution = failures * weight
        estimated_failures += contribution
        if count < 10:
            thin.append(name)
        contributions.append(
            {
                "stratum": name,
                "scored": count,
                "failures": failures,
                "sampling_rate": round(rate, 6),
                "each_stands_for": round(weight, 3),
                "estimated_population_failures": round(contribution, 3),
            }
        )

    population = sum(seen.values()) or sum(counts_by_stratum.values())
    return {
        "measurable": True,
        "population": population,
        "scored": sum(counts_by_stratum.values()),
        "raw_sample_failure_rate": round(
            sum(failures_by_stratum.values()) / sum(counts_by_stratum.values()), 6
        ),
        "estimated_population_failure_rate": (
            round(estimated_failures / population, 6) if population else None
        ),
        "by_stratum": contributions,
        "thin_strata": sorted(thin),
        "statement": (
            f"raw sample rate {sum(failures_by_stratum.values()) / sum(counts_by_stratum.values()):.1%}, "
            f"estimated population rate "
            f"{estimated_failures / population:.2%} across {population} trace(s)"
            if population
            else "no population to project onto"
        )
        + (
            f". {len(thin)} stratum/strata rest on fewer than 10 scored traces "
            f"({', '.join(sorted(thin))}), so their contribution is a wide guess."
            if thin
            else "."
        ),
    }
