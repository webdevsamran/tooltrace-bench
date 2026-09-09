"""The pytest scorer's arithmetic, pinned operator by operator.

Mutation testing put `tooltrace/scoring/builtin.py` at a 57% mutation score:
23 of 54 mutants survived. The worst cluster was this scorer's core
calculation, where *every* operator survived --

    total = passed + failed + errors        # Add -> Sub survived
    ratio = passed / total if total else 0  # Div -> Mult survived
    score = 1.0 if ratio >= min_ratio and errors == 0 else round(ratio, 4)
                        # GtE -> Gt, GtE -> LtE, Eq -> NotEq, and -> or survived

-- meaning the number this benchmark publishes could have been computed by
subtraction, or by multiplying instead of dividing, or with an inverted
threshold, and the whole suite would still have been green.

They were untested because they were unreachable: the calculation sat inside
`_tests_pass`, welded to a `subprocess.run` of a real pytest in a temporary
workspace. Extracting `score_pytest_output` is what made these assertions
possible; each test below corresponds to a specific surviving mutant.
"""

from __future__ import annotations

import pytest
from tooltrace.scoring.builtin import score_pytest_output


def score(output: str, min_ratio: float = 0.8) -> float:
    return score_pytest_output(output, min_ratio).score


# --------------------------------------------------------- total = a + b + c


def test_total_sums_the_three_counts() -> None:
    """Kills `Add -> Sub` on `total = passed + failed + errors`.

    With subtraction, 6 passed / 3 failed gives total 3 and a ratio of 2.0 --
    a score above 1. The ratio has to be 6/9.
    """
    assert score("6 passed, 3 failed", min_ratio=0.99) == pytest.approx(0.6667, abs=1e-4)


def test_errors_count_toward_the_total_not_against_it() -> None:
    """The second `Add -> Sub` survivor, on the errors term."""
    assert score("6 passed, 2 error", min_ratio=0.99) == pytest.approx(0.75, abs=1e-4)


# ------------------------------------------------- ratio = passed / total


def test_ratio_divides_rather_than_multiplies() -> None:
    """Kills `Div -> Mult`.

    4 passed of 8 is 0.5. Multiplied it would be 32, which `round` would
    happily return as a score.
    """
    assert score("4 passed, 4 failed", min_ratio=0.99) == pytest.approx(0.5)


def test_no_tests_at_all_scores_zero_rather_than_dividing_by_zero() -> None:
    assert score("no tests ran", min_ratio=0.5) == 0.0


# ----------------------------------------- score = 1.0 if ratio >= min_ratio


def test_a_ratio_exactly_at_the_threshold_passes() -> None:
    """Kills `GtE -> Gt`. The boundary is inclusive: 0.8 meets a 0.8 bar."""
    assert score("8 passed, 2 failed", min_ratio=0.8) == 1.0


def test_a_ratio_below_the_threshold_does_not_pass() -> None:
    """Kills `GtE -> LtE`, which would invert the comparison entirely."""
    assert score("7 passed, 3 failed", min_ratio=0.8) == pytest.approx(0.7)


def test_a_perfect_run_still_fails_a_higher_bar() -> None:
    """A second angle on the inverted-comparison mutant."""
    assert score("9 passed, 1 failed", min_ratio=0.95) == pytest.approx(0.9)


# ------------------------------------------------------- and errors == 0


def test_errors_deny_full_marks_even_when_the_ratio_is_met() -> None:
    """Kills `Eq -> NotEq` and `and -> or` on the errors clause.

    A collection error means the suite did not fully execute, so a passing
    ratio among the tests that *did* run must not be reported as success.
    """
    assert score("18 passed, 2 error", min_ratio=0.5) == pytest.approx(0.9)


def test_zero_errors_with_a_met_ratio_is_full_marks() -> None:
    """The other side of `Eq -> NotEq`: no errors must mean the clause holds."""
    assert score("10 passed", min_ratio=0.5) == 1.0


def test_errors_alone_score_zero() -> None:
    assert score("3 error", min_ratio=0.5) == 0.0


# ----------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("=== 5 passed in 0.12s ===", 1.0),
        ("=== 5 passed, 5 failed in 1.2s ===", 0.5),
        ("", 0.0),
        ("collected 0 items", 0.0),
    ],
)
def test_real_pytest_summary_shapes(output: str, expected: float) -> None:
    assert score(output, min_ratio=0.75) == pytest.approx(expected)


def test_the_detail_string_reports_what_it_counted() -> None:
    """A score with no visible basis is not auditable."""
    outcome = score_pytest_output("7 passed, 2 failed, 1 error", 0.9)
    assert "passed=7" in outcome.detail
    assert "failed=2" in outcome.detail
    assert "errors=1" in outcome.detail
