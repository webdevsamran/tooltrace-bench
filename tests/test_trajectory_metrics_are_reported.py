"""Trajectory metrics must reach a user, and must detect something.

`tooltrace/metrics/` shipped ten functions covering trajectory efficiency, loop
detection, hallucinated resources, verification quality, policy compliance and
the failure taxonomy. Every one of them had unit tests. **None of them had a
caller outside the test suite** — no runner, CLI command, report, bundle field
or web page ever computed them — so `tooltrace benchmark` reported success rates
and latency and nothing about *how* the agent got there.

That is the gap the wider field keeps naming: evaluation that examines whole
trajectories, error recovery, and whether an agent reached its score by a
sensible route. The code was written; it just was not reachable.

These tests pin both halves: the numbers appear in the benchmark summary, and
they change when the trajectory changes. A metric that reports the same value
whatever the agent did is decoration.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from tooltrace.core.models import FailureReason, TraceEvent
from tooltrace.metrics.aggregate import (
    aggregate_trajectory,
    failure_taxonomy,
    tool_events_from_trace,
    trajectory_report,
)
from tooltrace.runners.benchmark import run_benchmark
from tooltrace.runners.runner import TaskRunner
from tooltrace.tasks import load_all_tasks

_PERTURBED = "failure-recovery/retry-after-tool-failure"
_SIMPLE = "file-editing/fix-config-typo"


def _task(task_id: str):
    return next(t for t in load_all_tasks() if t.id == task_id)


def _run(task_id: str):
    task = _task(task_id)
    script = task.metadata.get("scripted_script")
    config = {"script": script} if isinstance(script, list) else None
    result, events, _ = TaskRunner().run(task, "scripted", config)
    return task, result, events


def _event(seq: int, type_: str, payload: dict[str, Any]) -> TraceEvent:
    return TraceEvent(timestamp="2026-01-01T00:00:00Z", seq=seq, type=type_, payload=payload)


# --- the wiring -------------------------------------------------------------


def test_benchmark_summary_carries_trajectory_metrics() -> None:
    bench = run_benchmark([_task(_SIMPLE)], "scripted", runs=2)
    overall = bench.summary["overall"]
    assert "trajectory" in overall, "benchmark still reports no trajectory metrics"
    trajectory = overall["trajectory"]
    assert trajectory["runs"] == 2
    for key in (
        "efficiency_mean",
        "stagnating_runs",
        "hallucinated_resource_events",
        "policy_violating_runs",
        "unverified_success_runs",
    ):
        assert key in trajectory, f"{key} missing from the trajectory block"


def test_every_task_gets_its_own_trajectory_block() -> None:
    bench = run_benchmark([_task(_SIMPLE), _task(_PERTURBED)], "scripted", runs=1)
    for task_id, summary in bench.summary["per_task"].items():
        assert "trajectory" in summary, f"{task_id} has no trajectory block"
        assert summary["trajectory"]["runs"] == 1


def test_the_summary_says_how_runs_failed() -> None:
    bench = run_benchmark([_task(_SIMPLE)], "scripted", runs=1)
    taxonomy = bench.summary["overall"]["failure_taxonomy"]
    assert taxonomy == {"none": 1}


def test_the_summary_is_json_serialisable() -> None:
    """It travels through `--json`, the report writers and the web data."""
    bench = run_benchmark([_task(_SIMPLE)], "scripted", runs=1)
    assert json.loads(json.dumps(bench.summary))


# --- pairing ---------------------------------------------------------------


def test_requests_and_results_are_paired_into_one_record() -> None:
    """The metrics want one record per call; the trace stores two events."""
    _, _, events = _run(_PERTURBED)
    paired = tool_events_from_trace(events)
    assert paired, "no tool calls were paired"
    for call in paired:
        assert call["tool"], "a paired call lost its tool name"
        assert call["status"] in {"ok", "error", "denied"}, call["status"]
    requests = sum(1 for e in events if e.type == "tool_request")
    assert len(paired) == requests


def test_an_unanswered_request_is_not_paired() -> None:
    """A truncated trace must not invent an outcome for a call that has none."""
    events = [
        _event(1, "tool_request", {"tool": "read_file", "args_summary": "a"}),
        _event(2, "tool_result", {"tool": "read_file", "status": "ok"}),
        _event(3, "tool_request", {"tool": "write_file", "args_summary": "b"}),
    ]
    paired = tool_events_from_trace(events)
    assert len(paired) == 1
    assert paired[0]["tool"] == "read_file"


# --- non-vacuousness: the metrics must react to the trajectory --------------


def test_a_hallucinated_resource_is_counted() -> None:
    events = [
        _event(1, "tool_request", {"tool": "read_file", "args_summary": "missing.txt"}),
        _event(
            2,
            "tool_result",
            {"tool": "read_file", "status": "error", "error": "no such file: missing.txt"},
        ),
    ]
    task = _task(_SIMPLE)
    _, result, _ = _run(_SIMPLE)
    report = trajectory_report(result, events, task)
    assert report["hallucinated_resources"]["count"] == 1


def test_a_repeated_call_is_reported_as_stagnation() -> None:
    events: list[TraceEvent] = []
    seq = 1
    for _ in range(4):
        events.append(_event(seq, "tool_request", {"tool": "read_file", "args_summary": "same"}))
        seq += 1
        events.append(_event(seq, "tool_result", {"tool": "read_file", "status": "ok"}))
        seq += 1
    _, result, _ = _run(_SIMPLE)
    report = trajectory_report(result, events, _task(_SIMPLE))
    assert report["loop"]["is_stagnating"] is True


def test_a_denied_call_is_a_policy_violation() -> None:
    events = [
        _event(1, "tool_request", {"tool": "shell", "args_summary": "rm -rf /"}),
        _event(
            2,
            "tool_result",
            {"tool": "shell", "status": "denied", "error": "not allowed by task policy"},
        ),
    ]
    _, result, _ = _run(_SIMPLE)
    report = trajectory_report(result, events, _task(_SIMPLE))
    assert report["policy"]["compliant"] is False
    assert report["policy"]["denied_calls"] == 1


def test_a_clean_run_reports_no_violations() -> None:
    """The mirror of the above: the metrics must not cry wolf on a good run."""
    task, result, events = _run(_SIMPLE)
    report = trajectory_report(result, events, task)
    assert report["policy"]["compliant"] is True
    assert report["hallucinated_resources"]["count"] == 0
    assert report["loop"]["is_stagnating"] is False


# --- honesty ---------------------------------------------------------------


def test_an_unmeasured_quantity_aggregates_to_none_not_zero() -> None:
    """The scripted agent reports no tokens, so token efficiency is unknown."""
    task, result, events = _run(_SIMPLE)
    report = trajectory_report(result, events, task)
    aggregated = aggregate_trajectory([report, report])
    assert aggregated["efficiency_mean"]["score_per_1k_tokens"] is None
    assert aggregated["efficiency_mean"]["score_per_step"] is not None


def test_aggregating_nothing_returns_nothing() -> None:
    assert aggregate_trajectory([]) == {}


@pytest.mark.parametrize("runs", [1, 3])
def test_the_run_count_is_reported_honestly(runs: int) -> None:
    task, result, events = _run(_SIMPLE)
    report = trajectory_report(result, events, task)
    assert aggregate_trajectory([report] * runs)["runs"] == runs


def test_failure_taxonomy_counts_each_class() -> None:
    _, ok_result, _ = _run(_SIMPLE)
    failed = ok_result.model_copy(update={"failure_reason": FailureReason.policy_violation})
    counts = failure_taxonomy([ok_result, failed, failed])
    assert counts == {"policy_violation": 2, "none": 1}
