"""Comparison and regression analysis between runs.

Rules:
- only bundles with identical ``compatibility_key`` (task protocol, trace
  schema, result schema) AND identical task id/version may be compared;
- metrics have a declared direction (higher/lower is better);
- regression thresholds come from a config dict and produce stable exit codes.
"""

from __future__ import annotations

from typing import Any

from tooltrace.bundles import load_bundle_result, read_manifest
from tooltrace.core.exceptions import ComparisonError
from tooltrace.core.models import EvalResult, MetricComparison, RegressionReport

# metric -> (extractor, direction)
_METRICS: dict[str, tuple[Any, str]] = {
    "score": (lambda r: r.score.total, "higher_is_better"),
    "success": (lambda r: 1.0 if r.success else 0.0, "higher_is_better"),
    "steps": (lambda r: float(r.steps), "lower_is_better"),
    "tool_calls": (lambda r: float(r.tool_calls), "lower_is_better"),
    "failed_tool_calls": (lambda r: float(r.failed_tool_calls), "lower_is_better"),
    "invalid_tool_calls": (lambda r: float(r.invalid_tool_calls), "lower_is_better"),
    "repeated_calls": (lambda r: float(r.repeated_calls), "lower_is_better"),
    "unnecessary_changes": (lambda r: float(r.unnecessary_changes), "lower_is_better"),
    "workspace_violations": (lambda r: float(r.workspace_violations), "lower_is_better"),
    "wall_ms": (lambda r: r.wall_ms, "lower_is_better"),
    "model_ms": (lambda r: r.model_ms if r.model_ms is not None else None, "lower_is_better"),
    "total_tokens": (
        lambda r: (
            float(r.usage.tokens.total_tokens)
            if r.usage.tokens and r.usage.tokens.total_tokens is not None
            else None
        ),
        "lower_is_better",
    ),
    "provider_cost_reported": (
        lambda r: (
            float(r.usage.provider_cost_reported)
            if r.usage.provider_cost_reported is not None
            else None
        ),
        "lower_is_better",
    ),
}


def _load_pair(baseline_dir, current_dir) -> tuple[EvalResult, EvalResult]:
    base = load_bundle_result(baseline_dir)
    curr = load_bundle_result(current_dir)
    base_key = str(read_manifest(baseline_dir).get("compatibility_key", ""))
    curr_key = str(read_manifest(current_dir).get("compatibility_key", ""))
    if base_key != curr_key:
        raise ComparisonError(
            f"incompatible result schemas: baseline {base_key!r} vs current {curr_key!r}"
        )
    if (base.task_id, base.task_version) != (curr.task_id, curr.task_version):
        raise ComparisonError(
            f"cannot compare different tasks/versions: "
            f"{base.task_id}@{base.task_version} vs {curr.task_id}@{curr.task_version}"
        )
    return base, curr


def compare_bundles(baseline_dir, current_dir, metrics: list[str] | None = None):
    """Compare two single-run bundles. Returns list[MetricComparison]."""
    base, curr = _load_pair(baseline_dir, current_dir)
    wanted = metrics or ["success", "score", "steps", "tool_calls", "wall_ms"]
    out: list[MetricComparison] = []
    for name in wanted:
        if name not in _METRICS:
            raise ComparisonError(f"unknown metric {name!r}; available: {sorted(_METRICS)}")
        extractor, direction = _METRICS[name]
        b = extractor(base)
        c = extractor(curr)
        delta = (c - b) if (b is not None and c is not None) else None
        out.append(
            MetricComparison(
                metric=name,
                baseline=b,
                current=c,
                delta=delta,
                direction=direction,  # type: ignore[arg-type]
            )
        )
    return out


def check_regression(
    baseline_dir,
    current_dir,
    thresholds: dict[str, dict[str, float]],
) -> RegressionReport:
    """Apply thresholds like {"score": {"min_delta": -0.05}, "wall_ms":
    {"max_increase_pct": 20}}. Higher-is-better metrics fail when they drop
    more than min_delta; lower-is-better metrics fail when they rise more
    than max_increase_pct relative to the baseline."""
    comparisons = compare_bundles(baseline_dir, current_dir, metrics=list(thresholds))
    passed_all = True
    for comp in comparisons:
        rules = thresholds.get(comp.metric, {})
        passed = True
        if comp.delta is not None:
            if "min_delta" in rules and comp.direction == "higher_is_better":
                passed = comp.delta >= rules["min_delta"]
            elif "max_increase_pct" in rules and comp.direction == "lower_is_better":
                base_val = comp.baseline or 0.0
                limit = base_val * (1 + rules["max_increase_pct"] / 100.0)
                passed = (comp.current or 0.0) <= limit + 1e-9
        elif rules:
            passed = False  # cannot evaluate without data — fail loudly
        comp.threshold = float(rules.get("min_delta", rules.get("max_increase_pct", 0)))
        comp.passed = passed
        passed_all = passed_all and passed
    return RegressionReport(
        baseline_id=str(baseline_dir),
        current_id=str(current_dir),
        compatibility_key=str(read_manifest(baseline_dir).get("compatibility_key", "")),
        comparisons=comparisons,
        passed=passed_all,
        exit_code=0 if passed_all else 8,
    )
