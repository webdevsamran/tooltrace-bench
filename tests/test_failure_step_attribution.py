"""A failure should say which step broke, not only what kind of failure it was.

`Classification` carried a reason, a rule and a detail string, and no reference
to the event it came from. "The run failed with a policy violation" is a
category; "it failed at seq 5, calling `shell`" is something a reader can open,
and it is what lets a UI jump straight to the step.

The fields are optional and defaulted, so every existing caller and every
already-stored classification stays valid, and nothing on `EvalResult` or in the
bundle layout changed — the attribution surfaces through the benchmark summary,
which is an unversioned dict.
"""

from __future__ import annotations

from typing import Any

import pytest
from tooltrace.analysis.failures import classify
from tooltrace.core.models import TraceEvent
from tooltrace.runners.benchmark import run_benchmark
from tooltrace.runners.runner import TaskRunner
from tooltrace.tasks import load_all_tasks


def _task(task_id: str):
    return next(t for t in load_all_tasks() if t.id == task_id)


def _event(seq: int, type_: str, payload: dict[str, Any]) -> TraceEvent:
    return TraceEvent(timestamp="2026-01-01T00:00:00Z", seq=seq, type=type_, payload=payload)


def test_a_denied_call_is_attributed_to_its_step() -> None:
    events = [
        _event(1, "tool_request", {"tool": "read_file"}),
        _event(2, "tool_result", {"tool": "read_file", "status": "ok"}),
        _event(3, "tool_request", {"tool": "shell"}),
        _event(4, "tool_result", {"tool": "shell", "status": "denied", "error": "not allowed"}),
    ]
    classification = classify(events)
    assert classification.reason.value == "policy_violation"
    assert classification.seq == 4
    assert classification.tool == "shell"


def test_an_unknown_tool_is_attributed_to_its_step() -> None:
    events = [
        _event(1, "tool_request", {"tool": "nope"}),
        _event(2, "tool_result", {"tool": "nope", "status": "error", "data": {"invalid": True}}),
    ]
    classification = classify(events)
    assert classification.reason.value == "hallucinated_resource"
    assert classification.seq == 2
    assert classification.tool == "nope"


def test_a_tool_error_is_attributed_to_the_first_failing_call() -> None:
    events = [
        _event(1, "tool_request", {"tool": "read_file"}),
        _event(2, "tool_result", {"tool": "read_file", "status": "error", "error": "boom"}),
    ]
    classification = classify(events)
    assert classification.seq == 2
    assert classification.tool == "read_file"


def test_a_run_that_did_not_fail_attributes_nothing() -> None:
    """Attribution on a passing run would invent a defect."""
    classification = classify([], succeeded=True, finish_reason="finished")
    assert classification.reason.value == "none"
    assert classification.seq is None
    assert classification.tool is None


def test_the_fields_default_so_existing_callers_are_unaffected() -> None:
    from tooltrace.analysis.failures import Classification
    from tooltrace.core.models import FailureReason

    legacy = Classification(FailureReason.execution, "rule", "detail")
    assert legacy.seq is None and legacy.tool is None


# --- surfaced where a user sees it ------------------------------------------


def test_a_clean_benchmark_reports_no_failure_steps() -> None:
    bench = run_benchmark([_task("file-editing/fix-config-typo")], "scripted", runs=1)
    assert bench.summary["overall"]["trajectory"]["failure_steps"] == []


def test_a_failing_run_reports_where_it_broke() -> None:
    """The whole point: the summary names the step, not just the class."""
    task = _task("security/indirect-injection-direct-harm")
    disallowed = [
        {"tool": "read_file", "args": {"path": "ticket.md"}},
        {"tool": "shell", "args": {"command": "echo x"}},
    ]
    result, events, _ = TaskRunner().run(task, "scripted", {"script": disallowed})
    from tooltrace.metrics.aggregate import trajectory_report

    step = trajectory_report(result, events, task)["failure_step"]
    assert step is not None
    assert step["tool"] == "shell"
    assert step["reason"] == "policy_violation"
    assert isinstance(step["seq"], int)


@pytest.mark.parametrize("field", ["seq", "tool", "reason", "rule", "detail"])
def test_the_reported_step_carries_everything_a_reader_needs(field: str) -> None:
    task = _task("security/indirect-injection-direct-harm")
    result, events, _ = TaskRunner().run(
        task,
        "scripted",
        {"script": [{"tool": "shell", "args": {"command": "echo x"}}]},
    )
    from tooltrace.metrics.aggregate import trajectory_report

    assert field in (trajectory_report(result, events, task)["failure_step"] or {})
