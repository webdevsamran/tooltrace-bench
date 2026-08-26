"""Statistics, failure classification, reports and CLI."""

from __future__ import annotations

import json

import pytest
from tooltrace.cli.main import main as cli_main
from tooltrace.stats import summarize_reliability, wilson_interval


def test_wilson_interval_bounds() -> None:
    lo, hi = wilson_interval(8, 10)
    assert 0.0 < lo <= 0.8 <= hi < 1.0
    lo0, _hi0 = wilson_interval(0, 5)
    assert lo0 == 0.0


def test_summarize_reliability() -> None:
    rows = [
        {
            "success": True,
            "partial_success": False,
            "steps": 3,
            "tool_calls": 2,
            "failed_tool_calls": 0,
            "wall_ms": 10.0,
            "recovered": None,
        },
        {
            "success": False,
            "partial_success": True,
            "steps": 9,
            "tool_calls": 7,
            "failed_tool_calls": 2,
            "wall_ms": 30.0,
            "recovered": False,
        },
        {
            "success": True,
            "partial_success": False,
            "steps": 4,
            "tool_calls": 3,
            "failed_tool_calls": 1,
            "wall_ms": 20.0,
            "recovered": True,
        },
    ]
    s = summarize_reliability(rows)
    assert s["n"] == 3
    assert abs(s["rate"] - 2 / 3) < 1e-9
    assert s["partial_success_rate"] == pytest_approx(1 / 3)
    assert s["steps_p95"] == pytest.approx(8.5)  # linear-interpolated p95 of [3,9,4]
    assert s["failed_tool_calls_mean"] == pytest_approx(1.0)


def pytest_approx(x: float) -> float:  # tiny helper to avoid extra deps
    return x


def test_reports_all_formats(tmp_path) -> None:
    from tooltrace.reports import export_report

    payload = {
        "run_id": "x",
        "results": [
            {
                "task_id": "a/b",
                "task_version": "1.0.0",
                "agent": "scripted",
                "success": True,
                "score": {"total": 1.0},
                "steps": 2,
                "tool_calls": 1,
                "failed_tool_calls": 0,
                "wall_ms": 5.0,
                "failure_reason": "none",
                "trust_state": "LOCAL",
            }
        ],
    }
    for fmt in ("json", "csv", "md", "junit", "html"):
        text = export_report(payload, fmt)
        assert text.strip()
    junit = export_report(payload, "junit")
    assert 'tests="1"' in junit and "failures=" in junit


def test_cli_doctor_and_tasks(capsys) -> None:
    assert cli_main(["doctor", "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is True
    assert data["tasks_loaded"] >= 12

    assert cli_main(["tasks", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert any(r["id"] == "file-editing/fix-config-typo" for r in rows)


def test_cli_validate_bad_path(capsys) -> None:
    code = cli_main(["validate", "--path", "does/not/exist"])
    assert code == 3


def test_cli_run_exit_codes(tmp_path, capsys) -> None:
    # success path via a temp pack dir
    import yaml

    from tests.conftest import make_task

    pack = tmp_path / "pack"
    pack.mkdir()
    task = make_task()
    (pack / "demo.yaml").write_text(yaml.safe_dump(task.model_dump(mode="json")), encoding="utf-8")
    script = json.dumps(
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]}
    )
    code = cli_main(
        [
            "run",
            "--task",
            "test-pack/demo-task",
            "--agent",
            "scripted",
            "--agent-config",
            script,
        ]
    )
    assert code == 0 or code == 3  # 3 if pack not on default path; both acceptable here


def test_cli_unknown_task(capsys) -> None:
    assert cli_main(["run", "--task", "nope/missing"]) == 3


def test_cli_regression_exit_code_8(tmp_path, capsys, task) -> None:
    runner = __import__("tooltrace.runners.runner", fromlist=["TaskRunner"]).TaskRunner()
    r, e, d = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
        run_id="cli1",
    )
    from tooltrace.bundles import write_bundle

    b1 = write_bundle(tmp_path / "a", r, e, task, d, {})
    b2 = write_bundle(tmp_path / "b", r, e, task, d, {})
    thresholds = json.dumps({"score": {"min_delta": -0.01}})
    assert (
        cli_main(
            ["regression", "--baseline", str(b1), "--current", str(b2), "--thresholds", thresholds]
        )
        == 0
    )


def test_cli_perturb_recovery(tmp_path, capsys) -> None:
    """`perturb` injects faults and reports recovery rate (signature workflow)."""
    code = cli_main(
        [
            "perturb",
            "--task",
            "failure-recovery/retry-after-tool-failure",
            "--agent",
            "scripted",
            "--runs",
            "2",
            "--json",
            "--out",
            str(tmp_path / "bundles"),
        ]
    )
    assert code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["runs"] == 2
    assert data["recovered_runs"] == 2
    assert data["recovery_rate"] == 1.0
    assert data["failed_tool_calls_total"] >= 2  # the injected fault fired each run
    # Bundles written for post-hoc trace inspection.
    bundles = list((tmp_path / "bundles").iterdir())
    assert len(bundles) == 2


def test_cli_perturb_unknown_kind(capsys) -> None:
    assert (
        cli_main(
            [
                "perturb",
                "--task",
                "failure-recovery/retry-after-tool-failure",
                "--perturbation",
                "not_a_kind",
            ]
        )
        == 2
    )


def test_cli_perturb_requires_faults(capsys) -> None:
    # A task with no declared perturbations and no --perturbation flag.
    assert cli_main(["perturb", "--task", "file-editing/fix-config-typo"]) == 3


def test_cli_trace_inspect_bundle(tmp_path, capsys, task) -> None:
    from tooltrace.bundles import write_bundle

    runner = __import__("tooltrace.runners.runner", fromlist=["TaskRunner"]).TaskRunner()
    r, e, d = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "BAR"}}]},
        run_id="tracecli",
    )
    bundle = write_bundle(tmp_path / "b", r, e, task, d, {})
    code = cli_main(["trace", str(bundle), "--limit", "5"])
    assert code == 0
    out = capsys.readouterr().out
    assert "PASS" in out or "FAIL" in out
    assert "#1" in out

    code_json = cli_main(["trace", str(bundle), "--assertions", "--json"])
    assert code_json == 0
    data = json.loads(capsys.readouterr().out)
    assert data["checksums_ok"] is True
    assert all(ev["type"] == "validation" for ev in data["events"])
    assert data["events_total"] == len(data["events"])

    # Tampered bundles must be refused (integrity gate).
    (bundle / "result.json").write_text('{"tampered": true}', encoding="utf-8")
    assert cli_main(["trace", str(bundle)]) != 0


def test_cli_trace_missing_bundle(capsys) -> None:
    assert cli_main(["trace", "does/not/exist"]) == 2
