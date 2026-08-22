"""End-to-end runner, bundles, replay, comparison and regression."""

from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import make_task
from tooltrace.bundles import load_bundle_result, verify_bundle, write_bundle
from tooltrace.compare import check_regression, compare_bundles
from tooltrace.core.models import Score
from tooltrace.runners.runner import TaskRunner


def test_runner_scripted_success(task) -> None:
    runner = TaskRunner()
    result, events, diff = runner.run(
        task,
        "scripted",
        {
            "script": [
                {
                    "tool": "patch_file",
                    "args": {"path": "notes.txt", "search": "FOO", "replace": "BAR"},
                },
            ]
        },
        run_id="t1",
    )
    assert result.success
    assert result.score.total == 1.0
    assert result.failure_reason.value == "none"
    types = [e.type for e in events]
    assert types[0] == "task_start" and types[-1] == "task_end"
    assert "tool_request" in types and "validation" in types
    assert "BAR" in diff or "+BAR" in diff or diff  # workspace changed


def test_runner_failure_classification(task) -> None:
    runner = TaskRunner()
    result, _events, _diff = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "other.txt", "content": "x"}}]},
        run_id="t2",
    )
    assert not result.success
    assert result.failure_reason.value != "none"


def test_bundle_roundtrip(tmp_path: Path, task) -> None:
    runner = TaskRunner()
    result, events, diff = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
        run_id="b1",
    )
    bundle = write_bundle(tmp_path, result, events, task, diff, {"x": "y"})
    problems = verify_bundle(bundle)
    assert problems == []
    loaded = load_bundle_result(bundle)
    assert loaded.run_id == result.run_id

    # tamper detection
    (bundle / "result.json").write_text("{}", encoding="utf-8")
    assert verify_bundle(bundle)


def test_compare_bundles(tmp_path: Path, task) -> None:
    runner = TaskRunner()
    r1, e1, d1 = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
        run_id="c1",
    )
    r2, e2, d2 = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAD"}}]},
        run_id="c2",
    )
    b1 = write_bundle(tmp_path / "a", r1, e1, task, d1, {})
    b2 = write_bundle(tmp_path / "b", r2, e2, task, d2, {})
    comps = compare_bundles(b1, b2)
    by_metric = {c.metric: c for c in comps}
    assert by_metric["score"].delta < 0


def test_regression_thresholds(tmp_path: Path, task) -> None:
    runner = TaskRunner()
    r1, e1, d1 = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
        run_id="g1",
    )
    r2, e2, d2 = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "NOPE"}}]},
        run_id="g2",
    )
    b1 = write_bundle(tmp_path / "a", r1, e1, task, d1, {})
    b2 = write_bundle(tmp_path / "b", r2, e2, task, d2, {})

    ok_report = check_regression(b1, b2, {"score": {"min_delta": -1.0}})
    assert ok_report.passed and ok_report.exit_code == 0

    bad_report = check_regression(b1, b2, {"score": {"min_delta": -0.01}})
    assert not bad_report.passed and bad_report.exit_code == 8


def test_score_model_bounds() -> None:
    s = Score(total=0.5, components={"a": 1.0}, weights={"a": 0.5})
    assert s.total == 0.5
    import pytest

    with pytest.raises(ValueError):
        Score(total=1.5)


def test_replay_matches_clean_run(task) -> None:
    from tooltrace.replay import replay_trace

    runner = TaskRunner()
    _result, events, _diff = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "read_file", "args": {"path": "notes.txt"}}]},
        run_id="r1",
    )
    report = replay_trace(task, events)
    assert report.ok, report.mismatched + report.errors


def test_benchmark_json_serializable(task) -> None:
    from tooltrace.runners.benchmark import run_benchmark

    bench = run_benchmark([make_task()], "scripted", {"script": []}, runs=1)
    payload = json.loads(json.dumps(bench.model_dump(mode="json")))
    assert payload["summary"]["overall"]["n"] == 1
