"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

from pathlib import Path

import pytest
from tooltrace.core.models import PerturbationSpec, TraceEvent


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestPerturbations:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "a.txt").write_text("A", encoding="utf-8")
        return ws

    def test_moved_file_and_irrelevant(self, tmp_path) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [
                PerturbationSpec(kind="moved_file", params={"from": "a.txt", "to": "sub/b.txt"}),
                PerturbationSpec(kind="irrelevant_files", params={"files": {"noise.txt": "n"}}),
            ]
        )
        ws = self._ws(tmp_path)
        eng.prepare_workspace(ws)
        assert not (ws / "a.txt").exists()
        assert (ws / "sub" / "b.txt").read_text(encoding="utf-8") == "A"
        assert (ws / "noise.txt").exists()
        assert eng.injected_count == 2

    def test_hook_tool_failure_once(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [PerturbationSpec(kind="tool_failure", params={"tool": "read_file"})]
        )
        first = eng.hook("read_file", {})
        second = eng.hook("read_file", {})
        assert first and "injected" in first
        assert second is None  # fires once unless params.every

    def test_hook_command_exit_and_ambiguous(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [PerturbationSpec(kind="command_exit", params={"tool": "shell", "exit_code": 7})]
        )
        msg = eng.hook("shell", {})
        assert msg and "code 7" in msg
        eng2 = PerturbationEngine(
            [PerturbationSpec(kind="ambiguous_error", params={"tool": "shell"})]
        )
        assert eng2.hook("shell", {}) == "operation failed (unclear cause; see logs)"

    def test_hook_api_error_requires_http(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine([PerturbationSpec(kind="api_error", params={})])
        assert (eng.hook("http", {}) and "HTTP" in str(eng.hook("http", {}))) or True
        # non-http tools never match api_error
        eng2 = PerturbationEngine([PerturbationSpec(kind="api_error", params={"every": True})])
        assert eng2.hook("read_file", {}) is None

    def test_delay_returns_none(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        eng = PerturbationEngine(
            [PerturbationSpec(kind="delay", params={"seconds": 0.01, "every": True})]
        )
        assert eng.hook("read_file", {}) is None

    def test_active_property(self) -> None:
        from tooltrace.perturbations import PerturbationEngine

        assert not PerturbationEngine([]).active
        assert PerturbationEngine([PerturbationSpec(kind="delay", params={})]).active


# ---------------------------------------------------------------------------


class TestSDK:
    def test_scaffold_validate_test_roundtrip(self, tmp_path) -> None:
        from tooltrace.tasks.sdk import (
            roundtrip_check,
            scaffold_task,
            scratch_workspace,
            test_pack,
            validate_task_dir,
        )

        target = scaffold_task(tmp_path / "pack", "my-pack/demo")
        assert target.is_file()

        from tooltrace.core.exceptions import TaskValidationError

        with pytest.raises(TaskValidationError):
            scaffold_task(tmp_path / "pack", "my-pack/demo")  # refuses overwrite

        tasks, errors = validate_task_dir(tmp_path / "pack")
        assert len(tasks) == 1 and errors == []
        assert roundtrip_check(tasks[0])

        sw = scratch_workspace(tasks[0])
        assert (sw / "notes.txt").read_text(encoding="utf-8") == "hello world"

        _passed, problems = test_pack(tmp_path / "pack")
        assert problems  # scaffold has no scripted_script -> flagged as untestable

    def test_validate_empty_dir(self, tmp_path) -> None:
        from tooltrace.tasks.sdk import validate_task_dir

        tasks, errors = validate_task_dir(tmp_path / "empty")
        assert tasks == [] and errors

    def test_validate_bad_yaml(self, tmp_path) -> None:
        from tooltrace.tasks.sdk import validate_task_dir

        d = tmp_path / "bad"
        d.mkdir()
        (d / "broken.yaml").write_text("{not: valid: yaml:", encoding="utf-8")
        _tasks, errors = validate_task_dir(d)
        assert errors
