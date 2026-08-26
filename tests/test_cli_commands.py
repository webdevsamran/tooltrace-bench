"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

import json
from pathlib import Path

from tooltrace.core.models import TraceEvent


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestCLICommands:
    def test_version_flag(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["--version"]) == 0
        assert capsys.readouterr().out.strip()

    def test_doctor_plain(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["doctor"]) == 0
        assert "ok" in capsys.readouterr().out.lower() or "True" in capsys.readouterr().out

    def test_tasks_category_filter(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["tasks", "--category", "file-editing"]) == 0
        assert "fix-config-typo" in capsys.readouterr().out

    def test_agents_list(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["agents", "--json"]) == 0
        rows = json.loads(capsys.readouterr().out)
        assert {r["name"] for r in rows} >= {"scripted", "subprocess"}

    def test_report_formats_from_results(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        for fmt in ("json", "md", "junit"):
            assert (
                main(
                    [
                        "report",
                        "--bundles",
                        "results",
                        "--format",
                        fmt,
                        "--output",
                        str(tmp_path / f"r.{fmt}"),
                    ]
                )
                == 0
            )
            assert (tmp_path / f"r.{fmt}").stat().st_size > 0

    def test_html_report_embeds_timeline(self, tmp_path) -> None:
        from tooltrace.cli.main import main

        out = tmp_path / "r.html"
        assert (
            main(["report", "--bundles", "results", "--format", "html", "--output", str(out)]) == 0
        )
        text = out.read_text(encoding="utf-8")
        assert "Trace timeline" in text and "Workspace diff" in text

    def test_baseline_and_regression_flow(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        bundles = sorted(Path("results").rglob("*.tooltrace"))
        assert len(bundles) >= 2
        # regression only compares identical task/protocol versions — pair by
        # the task recorded inside each bundle (dir names are not unique keys:
        # shared output dirs like results/_smoke mix tasks).
        from tooltrace.bundles import load_bundle_result

        by_task: dict[str, list[Path]] = {}
        for b in bundles:
            try:
                tid = str(load_bundle_result(b).task_id)
            except Exception:
                continue
            by_task.setdefault(tid, []).append(b)
        pair = next(v for v in by_task.values() if len(v) >= 2)
        assert main(["baseline", "--name", "ci-base", "--bundle", str(pair[0]), "--json"]) == 0
        reg = json.loads(capsys.readouterr().out)
        assert reg["baseline"] == "ci-base"
        thresholds = json.dumps({"score": {"min_delta": -1.0}})
        code = main(
            [
                "regression",
                "--baseline",
                str(pair[0]),
                "--current",
                str(pair[1]),
                "--thresholds",
                thresholds,
                "--json",
            ]
        )
        assert code in (0, 8)

    def test_compare_incompatible_errors(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(["compare", "--baseline", "nope/a.tooltrace", "--current", "nope/b.tooltrace"])
        assert code == 2

    def test_export_plugins(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(["export", "--out", str(tmp_path / "exp")])
        assert code == 0

    def test_serve_missing_dist(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["serve", "--dir", "does/not/exist"]) == 2

    def test_unknown_metric_compare(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        bundles = sorted(Path("results").rglob("*.tooltrace"))
        if len(bundles) >= 2:
            code = main(
                [
                    "compare",
                    "--baseline",
                    str(bundles[0]),
                    "--current",
                    str(bundles[1]),
                    "--metrics",
                    "bogus",
                ]
            )
            assert code == 2

    def test_showdown_two_agents(self, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            [
                "showdown",
                "--agents",
                "scripted,scripted",
                "--task",
                "file-editing/fix-config-typo",
                "--runs",
                "1",
                "--json",
            ]
        )
        assert code == 0
        rows = json.loads(capsys.readouterr().out)
        assert len(rows) == 2 and rows[0]["success_rate"] == 1.0

    def test_benchmark_summary_and_gate(self, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            [
                "benchmark",
                "--agent",
                "scripted",
                "--task",
                "file-editing/fix-config-typo",
                "--runs",
                "1",
                "--summary",
                "--min-success-rate",
                "1.0",
                "--json",
            ]
        )
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert "overall" in data["summary"]

    def test_run_writes_bundle(self, tmp_path, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            [
                "run",
                "--task",
                "file-editing/fix-config-typo",
                "--agent",
                "scripted",
                "--out",
                str(tmp_path / "runs"),
                "--json",
            ]
        )
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["result"]["success"] is True
        assert list((tmp_path / "runs").glob("*.tooltrace"))
