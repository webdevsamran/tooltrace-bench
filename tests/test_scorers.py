"""Deterministic scorer behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tooltrace.scoring  # noqa: F401 - registers scorers
from tooltrace.core.registry import scorer_registry
from tooltrace.scoring.base import register_scorer


def run(name: str, params: dict, workspace: Path):
    return scorer_registry.get(name)(params, workspace)


def test_file_contains(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    assert run("file_contains", {"path": "a.txt", "text": "world"}, tmp_path).score == 1.0
    assert run("file_contains", {"path": "a.txt", "text": "nope"}, tmp_path).score == 0.0


def test_json_schema(tmp_path: Path) -> None:
    (tmp_path / "d.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
    schema = {"type": "object", "required": ["n"]}
    assert run("json_schema", {"path": "d.json", "schema": schema}, tmp_path).score == 1.0
    (tmp_path / "bad.json").write_text("{oops", encoding="utf-8")
    assert run("json_schema", {"path": "bad.json", "schema": schema}, tmp_path).score == 0.0


def test_csv_equals(tmp_path: Path) -> None:
    (tmp_path / "o.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    ok = run("csv_equals", {"path": "o.csv", "expected_csv": "a,b\r\n1,2\r\n"}, tmp_path)
    assert ok.score == 1.0
    bad = run("csv_equals", {"path": "o.csv", "expected_csv": "a,b\n9,9\n"}, tmp_path)
    assert bad.score == 0.0


def test_ast_check(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def alpha():\n    pass\n", encoding="utf-8")
    r = run("ast_check", {"path": "m.py", "defines": ["alpha"], "not_defines": ["beta"]}, tmp_path)
    assert r.score == 1.0
    r2 = run("ast_check", {"path": "m.py", "defines": ["missing_fn"]}, tmp_path)
    assert r2.score == 0.0


def test_data_equals_normalizes_whitespace(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("line1  \nline2\n", encoding="utf-8")
    r = run("data_equals", {"path": "f.txt", "expected": "line1\nline2"}, tmp_path)
    assert r.score == 1.0


def test_command_exit(tmp_path: Path) -> None:
    r = run("command_exit", {"command": "exit 3", "expect_code": 3}, tmp_path)
    assert r.score == 1.0


def test_custom_scorer_registration() -> None:
    @register_scorer("_test_always_pass")
    def _always(params, workspace):  # type: ignore[no-untyped-def]
        from tooltrace.scoring.base import ScorerOutcome

        return ScorerOutcome(1.0, "ok")

    assert "_test_always_pass" in scorer_registry.names()


def test_unknown_scorer_raises(workspace: Path) -> None:
    with pytest.raises(KeyError):
        scorer_registry.get("definitely-not-a-scorer")
