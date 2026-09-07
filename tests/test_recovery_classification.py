"""A successful run has no failure reason, however it got there (#16).

`classify()` returned `execution / unrecovered_injected_fault` whenever any
tool result carried an injected fault, regardless of whether the agent then
recovered. Recovery tasks therefore reported `success=True` alongside
`failure_reason=execution` and a detail saying "unrecovered" -- a
contradiction, since the agent plainly did recover or the assertions would not
all have scored 1.0. Every committed sample result carried it, and the
frontend rendered "PASS ... execution".
"""

from __future__ import annotations

import itertools

from tooltrace.analysis.failures import classify
from tooltrace.core.models import FailureReason, TraceEvent

_SEQ = itertools.count()


def _injected_error(tool: str = "read_file") -> TraceEvent:
    return TraceEvent(
        timestamp="2026-09-07T00:00:00+00:00",
        seq=next(_SEQ),
        type="tool_result",
        payload={
            "tool": tool,
            "status": "error",
            "error": f"injected transient failure of tool {tool}",
            "data": {"injected": True},
        },
    )


def _ok(tool: str = "read_file") -> TraceEvent:
    return TraceEvent(
        timestamp="2026-09-07T00:00:00+00:00",
        seq=next(_SEQ),
        type="tool_result",
        payload={"tool": tool, "status": "ok", "data": {}},
    )


def test_recovered_run_has_no_failure_reason() -> None:
    """The headline regression."""
    result = classify(
        [_injected_error(), _ok(), _ok()],
        finish_reason="finished",
        score_total=1.0,
        succeeded=True,
    )
    assert result.reason is FailureReason.none
    assert result.rule == "no_failure"


def test_multiple_recovered_faults_still_report_no_failure() -> None:
    events = [_injected_error("read_file"), _ok(), _injected_error("shell"), _ok("shell")]
    result = classify(events, finish_reason="finished", score_total=1.0, succeeded=True)
    assert result.reason is FailureReason.none


def test_an_unrecovered_fault_is_still_reported() -> None:
    """The fix must not swallow genuine failures."""
    result = classify(
        [_injected_error()],
        finish_reason="finished",
        score_total=0.0,
        succeeded=False,
    )
    assert result.reason is FailureReason.execution
    assert result.rule == "unrecovered_injected_fault"


def test_a_timeout_still_wins_over_success() -> None:
    """A timed-out run is a failure even if assertions happened to pass."""
    result = classify([], finish_reason="finished", score_total=1.0, succeeded=True, timed_out=True)
    assert result.reason is FailureReason.timeout


def test_max_steps_is_not_masked_by_a_full_score() -> None:
    """Only finish_reason='finished' short-circuits; exhaustion is a failure."""
    result = classify([], finish_reason="max_steps", score_total=1.0, succeeded=True)
    assert result.reason is FailureReason.context_loss


def test_partial_success_is_not_treated_as_success() -> None:
    result = classify(
        [_injected_error()],
        finish_reason="finished",
        score_total=0.6,
        succeeded=False,
    )
    assert result.reason is not FailureReason.none


def test_no_committed_result_contradicts_itself() -> None:
    """Guard the artifacts, not just the function."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    offenders = []
    for path in (root / "results").rglob("result.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("success") and data.get("failure_reason") not in (None, "none"):
            offenders.append(f"{path.name}: success but reason={data['failure_reason']}")
    assert not offenders, "committed results contradict themselves: " + "; ".join(offenders)
