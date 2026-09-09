"""One trace, one sequence.

The runner and the executor each kept their own event counter. The runner
handed the executor its current value as `seq_start` -- by value, at
construction -- and both then advanced independently. Every shipped bundle
carried duplicated sequence numbers (five duplicates in a twelve-event trace)
and `seq` was not even monotonic in file order.

That matters beyond tidiness: `replay_from_checkpoint` partitions a trace on
`e.seq >= checkpoint_seq`, so it was partitioning on an ambiguous key, and the
trace is the artifact every reproducibility claim in this project rests on.

The corpus test below is the one that would have caught it at authoring time.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from tooltrace.replay import replay_from_checkpoint, replay_trace
from tooltrace.runners.runner import TaskRunner
from tooltrace.tasks import load_all_tasks

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"

_PERTURBED_TASK = "failure-recovery/retry-after-tool-failure"


def _run(task_id: str):
    task = next(t for t in load_all_tasks() if t.id == task_id)
    script = task.metadata.get("scripted_script")
    config = {"script": script} if isinstance(script, list) else None
    _, events, _ = TaskRunner().run(task, "scripted", config)
    return task, events


@pytest.mark.parametrize(
    "task_id",
    [_PERTURBED_TASK, "file-editing/fix-config-typo", "multi-step-planning/clean-orders"],
)
def test_a_fresh_run_numbers_events_1_to_n(task_id: str) -> None:
    _, events = _run(task_id)
    seqs = [e.seq for e in events]
    assert seqs == list(range(1, len(seqs) + 1)), f"{task_id} produced {seqs}"


def _committed_traces() -> list[Path]:
    return sorted(_RESULTS.glob("*.tooltrace/trace.jsonl"))


def test_every_committed_bundle_has_unique_gapless_seq() -> None:
    traces = _committed_traces()
    if not traces:
        pytest.skip("no committed bundles in results/")
    problems = []
    for trace in traces:
        seqs = []
        for line in trace.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seqs.append(json.loads(line).get("seq"))
        duplicates = {s: n for s, n in Counter(seqs).items() if n > 1 and s is not None}
        if duplicates:
            problems.append(f"{trace.parent.name}: duplicate seq {duplicates}")
        elif seqs != list(range(1, len(seqs) + 1)):
            problems.append(f"{trace.parent.name}: not 1..n monotonic -> {seqs}")
    assert not problems, "\n".join(problems)


def test_checkpoint_partition_skips_exactly_the_prefix() -> None:
    task, events = _run(_PERTURBED_TASK)
    for checkpoint in (2, 5, 7):
        expected_prefix = sum(1 for e in events if e.seq is not None and e.seq < checkpoint)
        report = replay_from_checkpoint(task, events, checkpoint)
        note = next(n for n in report.notes if n.startswith("partial-replay:"))
        assert f"skipped {expected_prefix} events" in note


def test_a_faithful_partial_replay_reports_ok() -> None:
    """`ok` was unreachable: the informational note was stored in `errors`."""
    task, events = _run(_PERTURBED_TASK)
    report = replay_from_checkpoint(task, events, 5)
    assert report.errors == []
    assert report.ok is True
    assert report.notes


def test_replay_injects_the_faults_the_task_declares() -> None:
    """The engine was built and its workspace prepared, but its hook was never
    wired to the executor, so any task carrying a perturbation replayed as a
    mismatch -- including this repository's own recovery task."""
    task, events = _run(_PERTURBED_TASK)
    assert task.perturbations, "this test needs a task that declares a fault"
    report = replay_trace(task, events)
    assert report.mismatched == []
    assert report.ok is True
    assert report.matched == report.total_requests > 0


def test_partial_replay_does_not_refire_a_spent_one_shot_fault() -> None:
    """A one-shot fault consumed by the skipped prefix must stay consumed."""
    task, events = _run(_PERTURBED_TASK)
    for checkpoint in (2, 5, 7):
        report = replay_from_checkpoint(task, events, checkpoint)
        assert report.mismatched == [], f"checkpoint {checkpoint}: {report.mismatched}"
