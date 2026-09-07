"""Bootstrap intervals and flakiness detection (#15).

Wilson is for proportions; applying it to steps or latency is a category
error, and a normal approximation assumes a symmetry that latency does not
have -- it is right-skewed, so a symmetric interval understates the upper tail
exactly where it matters. These tests check the properties that make the
intervals worth reporting, not just that the functions return numbers.
"""

from __future__ import annotations

import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from tooltrace.analysis.stats import (
    bootstrap_interval,
    runs_test,
    summarize_reliability,
)

_SAMPLES = st.lists(
    st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    min_size=2,
    max_size=60,
)


@given(_SAMPLES)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_interval_brackets_the_observed_mean(values: list[float]) -> None:
    """A bootstrap interval for the mean must contain the sample mean."""
    interval = bootstrap_interval(values)
    assert interval is not None
    observed = sum(values) / len(values)
    low, high = interval
    assert low <= observed <= high, f"{observed} outside [{low}, {high}]"


@given(_SAMPLES)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_interval_lies_within_the_observed_range(values: list[float]) -> None:
    """Resampling cannot produce a mean outside the data's own range.

    Compared with a relative tolerance rather than exactly: summing floats to
    take a mean can land one ULP outside the range that produced them, which
    hypothesis found immediately with a sample of repeated large values. That
    is float accumulation, not a property violation.
    """
    low, high = bootstrap_interval(values)
    lo, hi = min(values), max(values)
    tolerance = max(abs(lo), abs(hi)) * 1e-9
    assert lo - tolerance <= low <= high <= hi + tolerance


@given(_SAMPLES)
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_bca_also_brackets_the_mean(values: list[float]) -> None:
    interval = bootstrap_interval(values, method="bca")
    assert interval is not None
    observed = sum(values) / len(values)
    assert interval[0] <= observed <= interval[1]


def test_a_wider_confidence_level_gives_a_wider_interval() -> None:
    values = [1.0, 2.0, 3.0, 10.0, 4.0, 2.5, 3.5, 20.0, 1.5, 6.0]
    narrow = bootstrap_interval(values, confidence=0.80)
    wide = bootstrap_interval(values, confidence=0.99)
    assert (wide[1] - wide[0]) >= (narrow[1] - narrow[0])


def test_identical_observations_give_a_degenerate_interval() -> None:
    low, high = bootstrap_interval([7.0] * 12)
    assert low == high == 7.0


def test_a_single_observation_has_no_interval() -> None:
    """One point cannot support an interval; returning one would invent it."""
    assert bootstrap_interval([1.0]) is None
    assert bootstrap_interval([]) is None


def test_bootstrap_is_deterministic() -> None:
    """A benchmark that reports a different CI each run is not reproducible."""
    values = [random.Random(1).uniform(0, 100) for _ in range(30)]
    assert bootstrap_interval(values) == bootstrap_interval(values)


def test_unknown_method_is_rejected() -> None:
    with pytest.raises(ValueError, match="percentile or bca"):
        bootstrap_interval([1.0, 2.0], method="nonsense")


@given(st.integers(min_value=0, max_value=200), st.integers(min_value=1, max_value=60))
@settings(max_examples=40, deadline=None)
def test_coverage_on_synthetic_data(seed: int, n: int) -> None:
    """Intervals must be well-formed on arbitrary synthetic samples."""
    rng = random.Random(seed)
    values = [rng.expovariate(1 / 50.0) for _ in range(max(2, n))]
    low, high = bootstrap_interval(values)
    assert low <= high
    assert low >= 0.0


# ------------------------------------------------------------------ flakiness


def test_alternating_outcomes_are_flagged_flaky() -> None:
    """Perfect alternation has far more runs than independence predicts."""
    result = runs_test([True, False] * 8)
    assert result["flaky"] is True
    assert result["z"] > 0
    assert "alternate" in result["reason"]


def test_clumped_outcomes_are_flagged() -> None:
    """All passes then all failures means something changed mid-sequence."""
    result = runs_test([True] * 8 + [False] * 8)
    assert result["flaky"] is True
    assert result["z"] < 0
    assert "clump" in result["reason"]


def test_a_plausible_mixed_sequence_is_not_flagged() -> None:
    result = runs_test([True, True, False, True, False, False, True, True])
    assert result["flaky"] is False


def test_all_passes_cannot_be_tested() -> None:
    """No failures means no independence claim to test -- report that, not a z."""
    result = runs_test([True] * 10)
    assert result["z"] is None
    assert result["flaky"] is False
    assert "not enough" in result["reason"]


def test_flakiness_distinguishes_two_identical_success_rates() -> None:
    """The point of the test: same rate, different stability."""
    alternating = [True, False] * 6  # 50%, maximally unstable
    clumped = [True] * 6 + [False] * 6  # 50%, one regime change
    assert runs_test(alternating)["flaky"] is True
    assert runs_test(clumped)["flaky"] is True
    assert runs_test(alternating)["z"] > 0 > runs_test(clumped)["z"]


# ------------------------------------------------------- summarize_reliability


def _runs(successes: list[bool]) -> list[dict[str, object]]:
    return [
        {
            "success": s,
            "partial_success": False,
            "steps": 3 if s else 6,
            "tool_calls": 2,
            "failed_tool_calls": 0 if s else 1,
            "wall_ms": 10.0 if s else 40.0,
        }
        for s in successes
    ]


def test_default_ci_method_is_unchanged() -> None:
    """The issue requires the default stay Wilson."""
    summary = summarize_reliability(_runs([True, True, False, True]))
    assert summary["ci_method"] == "wilson"


def test_bootstrap_ci_method_is_selectable() -> None:
    for method in ("percentile", "bca"):
        summary = summarize_reliability(_runs([True, True, False, True]), ci_method=method)
        assert summary["ci_method"] == method
        assert summary["ci_low"] <= summary["rate"] <= summary["ci_high"]


def test_unknown_ci_method_is_rejected() -> None:
    with pytest.raises(ValueError, match="wilson, percentile or bca"):
        summarize_reliability(_runs([True, False]), ci_method="nonsense")


def test_non_binary_metrics_get_intervals() -> None:
    """steps and wall_ms had no interval of any kind before."""
    summary = summarize_reliability(_runs([True, False, True, False, True]))
    assert "steps_ci95" in summary and "wall_ms_ci95" in summary
    assert summary["steps_ci95"][0] <= summary["steps_mean"] <= summary["steps_ci95"][1]


def test_flakiness_is_always_reported() -> None:
    summary = summarize_reliability(_runs([True, False] * 5))
    assert summary["flakiness"]["flaky"] is True
