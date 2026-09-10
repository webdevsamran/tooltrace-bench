"""Compare a pull request's runs against a baseline, without inventing a verdict.

`check_regression` in `tooltrace/analysis/compare.py` compares two **single-run**
bundles and fails a build when a metric moved past a threshold. For latency on a
deterministic task that is defensible. For a success rate it is not: one run is
one Bernoulli draw, and "the score dropped from 1.0 to 0.0" describes a coin
landing differently, not a regression. A gate like that either blocks pull
requests at random or gets switched off, and both outcomes are worse than no gate.

So this compares *samples* and reports one of four verdicts per metric:

- **`regressed`** — the interval on the difference excludes zero, in the bad
  direction.
- **`improved`** — the same, in the good direction.
- **`no_change_detected`** — the interval contains zero *and* is tight enough
  that a change worth caring about would have shown up.
- **`inconclusive`** — the interval contains zero and is too wide to rule such a
  change out. Nothing was learned, and saying so is the point.

The fourth verdict is the one that makes the other three trustworthy. Without it,
"no regression" covers both "we checked" and "we could not tell", and a green
check on 3 runs would mean the same thing as a green check on 300.

Only `regressed` fails a build. An inconclusive comparison is reported loudly and
does not block: blocking on the absence of evidence would make the gate a
function of how many runs someone could afford, not of whether the code got worse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tooltrace.analysis.stats import bootstrap_interval, wilson_interval

#: Metrics compared, with the direction that counts as worse and the smallest
#: change worth blocking a pull request over. `min_effect` is what separates
#: `no_change_detected` from `inconclusive`: an interval that cannot exclude a
#: change this large has not established anything.
METRICS: dict[str, dict[str, Any]] = {
    "success_rate": {"direction": "higher_is_better", "min_effect": 0.10, "kind": "proportion"},
    "score": {"direction": "higher_is_better", "min_effect": 0.10, "kind": "mean"},
    "steps": {"direction": "lower_is_better", "min_effect": 1.0, "kind": "mean"},
    "failed_tool_calls": {"direction": "lower_is_better", "min_effect": 0.5, "kind": "mean"},
    # Latency has no absolute threshold worth stating: 5 ms is nothing on a
    # 4-second task and everything on a 6 ms one. So its minimum effect is a
    # share of the baseline. A fixed 0 here would have made latency the one
    # metric that can never be inconclusive, which is backwards -- it is the
    # noisiest of the five.
    "wall_ms": {
        "direction": "lower_is_better",
        "min_effect_pct": 0.20,
        "kind": "mean",
    },
    # Tokens, for the same reason as latency and with the same shape of
    # threshold. A prompt change that leaves every score identical and doubles
    # the token count is a regression -- it costs money on every future run --
    # and no other metric here would notice it. 15% of the baseline, because
    # token counts are less noisy than wall time: nothing else is competing for
    # the provider's tokeniser.
    #
    # A run that reports no usage contributes no value rather than a zero. A
    # provider that says nothing about tokens must not read as one that used
    # none, which would turn "we stopped measuring" into a large improvement.
    "tokens_per_run": {
        "direction": "lower_is_better",
        "min_effect_pct": 0.15,
        "kind": "mean",
    },
}

REGRESSED = "regressed"
IMPROVED = "improved"
NO_CHANGE = "no_change_detected"
INCONCLUSIVE = "inconclusive"
#: Nobody reported this metric on either side. Distinct from `inconclusive`,
#: and the distinction changes what a reader should do: an inconclusive row
#: asks for more runs, a not-measured row asks for an adapter that reports the
#: number at all. Collapsing them would make a gate on token usage read as
#: permanently uncertain against every agent that never emits usage.
NOT_MEASURED = "not_measured"


@dataclass
class MetricVerdict:
    metric: str
    direction: str
    baseline: float | None
    current: float | None
    delta: float | None
    #: 95% interval on the *difference*, not on either side separately. Two
    #: overlapping per-side intervals do not imply the difference includes zero,
    #: and comparing them by eye is the most common way to get this wrong.
    delta_ci: list[float] | None
    baseline_n: int
    current_n: int
    verdict: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": self.direction,
            "baseline": self.baseline,
            "current": self.current,
            "delta": self.delta,
            "delta_ci95": self.delta_ci,
            "baseline_n": self.baseline_n,
            "current_n": self.current_n,
            "verdict": self.verdict,
            "note": self.note,
        }


@dataclass
class PRReport:
    verdicts: list[MetricVerdict] = field(default_factory=list)
    #: True only when at least one metric is `regressed`. Inconclusive never
    #: fails: blocking on absent evidence makes the gate a function of the
    #: caller's compute budget rather than of the change.
    regressed: bool = False
    baseline_runs: int = 0
    current_runs: int = 0
    incomparable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "regressed": self.regressed,
            "baseline_runs": self.baseline_runs,
            "current_runs": self.current_runs,
            "incomparable": self.incomparable,
            "metrics": [v.to_dict() for v in self.verdicts],
        }


def _values(rows: list[dict[str, Any]], metric: str) -> list[float]:
    if metric == "success_rate":
        return [1.0 if r.get("success") else 0.0 for r in rows]
    if metric == "score":
        return [
            float(r["score_total"]) for r in rows if isinstance(r.get("score_total"), int | float)
        ]
    return [float(r[metric]) for r in rows if isinstance(r.get(metric), int | float)]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _difference_interval(
    baseline: list[float], current: list[float], kind: str
) -> list[float] | None:
    """A 95% interval on `current - baseline`.

    For a proportion this uses the Newcombe method — the difference of two Wilson
    intervals — which behaves correctly at the boundaries where a bootstrap does
    not. A sample of ten perfect runs bootstraps to a zero-width interval, and
    "the rate is exactly 1.0 with no uncertainty" is the single most misleading
    thing this function could return.

    For a mean, bootstrapping each side and differencing the bounds is the
    conservative combination: it is wider than the true interval on the
    difference, which errs towards `inconclusive` rather than towards a
    confident regression.
    """
    if len(baseline) < 2 or len(current) < 2:
        return None

    if kind == "proportion":
        b_low, b_high = wilson_interval(int(sum(baseline)), len(baseline))
        c_low, c_high = wilson_interval(int(sum(current)), len(current))
        return [round(c_low - b_high, 6), round(c_high - b_low, 6)]

    b_interval = bootstrap_interval(baseline)
    c_interval = bootstrap_interval(current)
    if b_interval is None or c_interval is None:
        return None
    return [round(c_interval[0] - b_interval[1], 6), round(c_interval[1] - b_interval[0], 6)]


def _verdict_for(
    delta_ci: list[float] | None, direction: str, min_effect: float
) -> tuple[str, str]:
    """Turn an interval on the difference into one of four verdicts.

    Two independent questions have to both be answered yes before a build fails:
    is the change **real** (does the interval exclude zero), and is it **large
    enough to matter** (is the smallest change the data supports at least
    `min_effect`). Statistical significance alone is not enough. A deterministic
    task with no run-to-run variance can make a 0.1% latency shift certain, and
    failing a pull request on that is exactly the behaviour that gets a gate
    switched off.

    Symmetrically, an interval containing zero is only reassuring when it is
    tight: if it still permits a change worth caring about, nothing was learned.
    """
    if delta_ci is None:
        return INCONCLUSIVE, "fewer than two runs on one side; no interval can be computed"

    low, high = delta_ci
    worse = low > 0 if direction == "lower_is_better" else high < 0
    better = high < 0 if direction == "lower_is_better" else low > 0

    if worse or better:
        # The most conservative reading of the change: the interval bound
        # nearest zero. Using the point estimate would let a wide interval that
        # barely clears zero read as a large effect.
        smallest = min(abs(low), abs(high))
        if min_effect > 0 and smallest < min_effect:
            return (
                NO_CHANGE,
                f"a real difference was measured, but at least {smallest:.3f} and "
                f"below the {min_effect:.3f} that would matter -- not worth blocking on",
            )
        if worse:
            return REGRESSED, "the interval on the difference excludes zero in the worse direction"
        return IMPROVED, "the interval on the difference excludes zero in the better direction"

    # Zero is inside the interval. Whether that means "no change" or "cannot
    # tell" depends on how much of a change the interval still permits.
    permitted = high if direction == "lower_is_better" else -low
    if min_effect > 0 and permitted >= min_effect:
        return (
            INCONCLUSIVE,
            f"the interval still permits a change of {permitted:.3f}, at or beyond the "
            f"{min_effect:.3f} that would matter; more runs are needed to rule it out",
        )
    return (
        NO_CHANGE,
        "the interval on the difference contains zero and excludes a change that matters",
    )


def compare_samples(
    baseline_rows: list[dict[str, Any]],
    current_rows: list[dict[str, Any]],
    *,
    metrics: list[str] | None = None,
) -> PRReport:
    """Compare two sets of runs, metric by metric."""
    wanted = metrics or list(METRICS)
    report = PRReport(baseline_runs=len(baseline_rows), current_runs=len(current_rows))

    for metric in wanted:
        spec = METRICS.get(metric)
        if spec is None:
            report.incomparable.append(f"unknown metric {metric!r}")
            continue
        baseline = _values(baseline_rows, metric)
        current = _values(current_rows, metric)
        base_mean, curr_mean = _mean(baseline), _mean(current)
        delta = (
            round(curr_mean - base_mean, 6)
            if base_mean is not None and curr_mean is not None
            else None
        )
        interval = _difference_interval(baseline, current, str(spec["kind"]))
        # A relative threshold needs the baseline to resolve against; with no
        # baseline there is nothing to take a percentage of, and the comparison
        # is inconclusive for that reason alone.
        if "min_effect_pct" in spec:
            min_effect = abs(base_mean) * float(spec["min_effect_pct"]) if base_mean else 0.0
        else:
            min_effect = float(spec["min_effect"])
        if not baseline and not current:
            verdict, note = (
                NOT_MEASURED,
                "no run on either side reported this; it is unmeasured rather than uncertain",
            )
        else:
            verdict, note = _verdict_for(interval, str(spec["direction"]), min_effect)
        report.verdicts.append(
            MetricVerdict(
                metric=metric,
                direction=str(spec["direction"]),
                baseline=round(base_mean, 6) if base_mean is not None else None,
                current=round(curr_mean, 6) if curr_mean is not None else None,
                delta=delta,
                delta_ci=interval,
                baseline_n=len(baseline),
                current_n=len(current),
                verdict=verdict,
                note=note,
            )
        )

    report.regressed = any(v.verdict == REGRESSED for v in report.verdicts)
    return report


def cohort_problems(baseline_meta: dict[str, Any], current_meta: dict[str, Any]) -> list[str]:
    """Reasons these two sets should not be compared at all.

    A regression report across different task or protocol versions is comparing
    two different measurements and attributing the difference to the code. That
    is worse than no report, so it is refused rather than annotated.
    """
    problems = []
    for field_name, label in (
        ("compatibility_key", "artifact compatibility key"),
        ("task_ids", "task set"),
    ):
        left, right = baseline_meta.get(field_name), current_meta.get(field_name)
        if left and right and left != right:
            problems.append(f"{label} differs: {left!r} vs {right!r}")
    return problems


_SYMBOLS = {
    REGRESSED: "regressed",
    IMPROVED: "improved",
    NO_CHANGE: "no change detected",
    INCONCLUSIVE: "inconclusive",
    NOT_MEASURED: "not measured",
}


def render_markdown(report: PRReport, *, title: str = "Agent reliability") -> str:
    """A pull-request comment. Written to be read in five seconds.

    The verdict column is words, not arrows or colours: a comment gets quoted
    into a terminal, an email digest and a screen reader, and none of those carry
    a red circle.
    """
    lines = [f"### {title}", ""]

    if report.incomparable:
        lines += ["**Not compared.**"] + [f"- {problem}" for problem in report.incomparable] + [""]

    if report.regressed:
        lines.append("**A regression the sample supports.** Details below.")
    elif any(v.verdict == INCONCLUSIVE for v in report.verdicts):
        lines.append(
            "**No regression established, but not every metric could be checked.** "
            "An inconclusive row means the runs were too few to rule out a change "
            "that would matter, not that nothing changed."
        )
    else:
        lines.append("**No regression, and the sample was large enough to say so.**")

    unmeasured = [v.metric for v in report.verdicts if v.verdict == NOT_MEASURED]
    if unmeasured:
        # Said out loud rather than left as a row nobody reads. A metric no
        # adapter reports is a gap in the instrumentation, and more runs will
        # not close it.
        lines.append(
            f"No run reported {', '.join(f'`{m}`' for m in unmeasured)}, so "
            + ("that metric was" if len(unmeasured) == 1 else "those metrics were")
            + " not checked at all. More runs will not change that; an adapter that "
            "reports the number will."
        )

    lines += [
        "",
        f"{report.baseline_runs} baseline runs vs {report.current_runs} current runs.",
        "",
        "| Metric | Baseline | Current | Delta | 95% CI on the delta | Verdict |",
        "|---|---|---|---|---|---|",
    ]
    for verdict in report.verdicts:
        interval = (
            f"{verdict.delta_ci[0]:+.3f} to {verdict.delta_ci[1]:+.3f}"
            if verdict.delta_ci
            else "n/a"
        )
        lines.append(
            f"| `{verdict.metric}` "
            f"| {'n/a' if verdict.baseline is None else f'{verdict.baseline:.3f}'} "
            f"| {'n/a' if verdict.current is None else f'{verdict.current:.3f}'} "
            f"| {'n/a' if verdict.delta is None else f'{verdict.delta:+.3f}'} "
            f"| {interval} "
            f"| {_SYMBOLS[verdict.verdict]} |"
        )

    inconclusive = [v for v in report.verdicts if v.verdict == INCONCLUSIVE]
    if inconclusive:
        lines += ["", "<details><summary>Why some rows are inconclusive</summary>", ""]
        lines += [f"- `{v.metric}`: {v.note}" for v in inconclusive]
        lines += ["", "</details>"]

    lines += [
        "",
        "The interval is on the **difference**, not on either side separately: two "
        "overlapping per-side intervals do not imply the difference contains zero.",
    ]
    return "\n".join(lines) + "\n"


def _total_tokens(result: Any) -> float | None:
    """Total tokens for one run, or None when the adapter reported none.

    None rather than 0, and the difference is the whole point: a provider that
    says nothing about tokens is not one that used none. Coercing it would make
    "we stopped measuring" look like the largest efficiency win in the history
    of the project.
    """
    usage = getattr(result, "usage", None)
    tokens = getattr(usage, "tokens", None) if usage is not None else None
    if tokens is None:
        return None
    total = getattr(tokens, "total_tokens", None)
    if isinstance(total, int | float):
        return float(total)
    prompt = getattr(tokens, "prompt_tokens", None)
    completion = getattr(tokens, "completion_tokens", None)
    if isinstance(prompt, int | float) or isinstance(completion, int | float):
        return float((prompt or 0) + (completion or 0))
    return None


def rows_from_bundles(bundle_dirs: list[Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Result rows and cohort metadata from a directory of bundles."""
    from tooltrace.artifacts.bundles import load_bundle_result, read_manifest

    rows: list[dict[str, Any]] = []
    keys: set[str] = set()
    tasks: set[str] = set()
    for bundle in sorted(bundle_dirs):
        result = load_bundle_result(bundle)
        rows.append(
            {
                "success": result.success,
                "score_total": result.score.total,
                "steps": result.steps,
                "failed_tool_calls": result.failed_tool_calls,
                "wall_ms": result.wall_ms,
                "tokens_per_run": _total_tokens(result),
                "task_id": result.task_id,
            }
        )
        tasks.add(result.task_id)
        keys.add(str(read_manifest(bundle).get("compatibility_key") or ""))
    return rows, {
        "compatibility_key": sorted(keys)[0] if len(keys) == 1 else sorted(keys),
        "task_ids": sorted(tasks),
    }
