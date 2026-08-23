"""Tests for the final spec-gap fixes: long-context sweep, plugin entry
points, telemetry/exporter namespaces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestContextSweep:
    def _family(self):
        from tooltrace.tasks import load_all_tasks

        family = [t for t in load_all_tasks() if getattr(t, "long_context", False)]
        assert len(family) >= 3, "long-context scale family must exist"
        return family

    def test_context_sweep_runs_and_aggregates(self) -> None:
        from tooltrace.runners.benchmark import context_sweep

        sweep = context_sweep(self._family(), "scripted", runs=1)
        assert sweep["sizes"] == ["1000", "4000", "16000"]
        for size in sweep["sizes"]:
            row = sweep["per_size"][size]
            assert row["rate"] == 1.0  # scripted reference solution passes at every scale
            assert "wall_ms_p95" in row and "steps_mean" in row
        assert set(sweep["degradation"]) >= {"rate", "steps_mean"}

    def test_context_sweep_rejects_non_longcontext(self) -> None:
        from tests.conftest import make_task
        from tooltrace.runners.benchmark import context_sweep

        with pytest.raises(ValueError):
            context_sweep([make_task()], "scripted")

    def test_cli_context_sweep_flag(self, capsys) -> None:
        from tooltrace.cli.main import main

        code = main(
            ["benchmark", "--agent", "scripted", "--context-sweep", "--runs", "1", "--json"]
        )
        assert code == 0
        data = json.loads(capsys.readouterr().out)
        assert data["sizes"] == ["1000", "4000", "16000"]

    def test_longcontext_tasks_marked_and_versioned(self) -> None:
        for t in self._family():
            assert t.long_context is True
            assert int(t.metadata["context_chars"]) > 0  # type: ignore[arg-type]
            assert t.version == "1.0.0"


class TestPluginEntryPoints:
    def test_all_six_groups_resolve(self) -> None:
        from tooltrace.core.registry import ENTRY_POINT_GROUPS, discover_plugins

        found = {kind: discover_plugins(group) for kind, group in ENTRY_POINT_GROUPS.items()}
        assert len(found) == 6
        assert set(found["agents"]) >= {"scripted", "subprocess"}
        assert set(found["tools"]) >= {
            "read_file",
            "write_file",
            "patch_file",
            "list_directory",
            "search_text",
            "shell",
            "git",
            "calculator",
            "test_runner",
            "http",
        }
        assert set(found["scorers"]) >= {"file_contains", "tests_pass", "git_diff"}
        assert set(found["reporters"]) >= {"html_report", "junit_report"}
        assert set(found["sandboxes"]) >= {"local"}
        assert "builtin" in found["task_packs"]

    def test_doctor_reports_plugin_counts(self, capsys) -> None:
        from tooltrace.cli.main import main

        assert main(["doctor", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        plugins = data["plugins"]
        assert set(plugins) == {
            "agents",
            "tools",
            "task_packs",
            "scorers",
            "reporters",
            "sandboxes",
        }
        assert len(plugins["tools"]) >= 10


class TestTelemetryAndExporters:
    def test_telemetry_namespace(self) -> None:
        from tooltrace.telemetry import (
            UsageMetadata,
            p50,
            p95,
            summarize_reliability,
            wilson_interval,
        )

        assert p50([1.0, 2.0, 3.0]) == 2.0
        assert p95([1.0] * 100) == 1.0
        low, high = wilson_interval(1, 1)
        assert 0.0 < low <= high <= 1.0
        rows = [
            {
                "success": True,
                "partial_success": False,
                "steps": 2,
                "tool_calls": 1,
                "failed_tool_calls": 0,
                "wall_ms": 5.0,
                "recovered": None,
            }
        ]
        summary = summarize_reliability(rows)
        assert summary["rate"] == 1.0
        assert UsageMetadata.model_fields

    def test_exporters_register_and_run(self, tmp_path: Path) -> None:
        from tooltrace.exporters import (
            html_report,
            register_exporter,
            run_exporters,
        )

        payload = {"results": [], "summary": {}}
        produced = run_exporters(payload, tmp_path / "out")
        names = [Path(p).name for p in produced if not str(p).endswith("ERROR")]
        assert "report.html" in names and "report.json" in names

        def custom(payload, dest_dir):  # type: ignore[no-untyped-def]
            target = dest_dir / "custom.txt"
            target.write_text("hi", encoding="utf-8")
            return target

        register_exporter("custom", custom)
        out = tmp_path / "out2"
        produced2 = run_exporters(payload, out)
        assert any(p.endswith("custom.txt") for p in produced2)
        assert html_report  # built-in reporter exists
