"""Assertion-builder DSL: builders mirror built-in scorers exactly."""

from __future__ import annotations

import pytest
from tooltrace.core.models import TaskDefinition
from tooltrace.dsl import (
    api_state,
    assertions,
    ast_check,
    command_exit,
    csv_equals,
    custom,
    data_equals,
    file_contains,
    file_exists,
    file_not_contains,
    file_not_exists,
    git_diff,
    json_equals,
    json_schema,
    tests_pass,
)


def test_builders_produce_matching_scorer_types() -> None:
    a = file_contains("notes.txt", any_of=["BAR", "BAZ"], weight=2.0, description="d")
    assert a.type == "file_contains"
    assert a.params == {"path": "notes.txt", "any_of": ["BAR", "BAZ"]}
    assert a.weight == 2.0
    assert a.description == "d"
    assert file_exists("x").type == "file_exists"
    assert file_not_exists("x").type == "file_not_exists"
    assert file_contains("x").type == "file_contains"
    assert "text" not in file_contains("x").params
    assert file_not_contains("x", none_of=["a"]) == file_not_contains("x", none_of=["a"])
    assert json_schema("o.json", {"type": "object"}).type == "json_schema"
    assert json_equals("o.json", {"k": 1}).params["expected"] == {"k": 1}
    assert csv_equals("o.csv", "a,b\n1,2\n").params["expected_csv"].startswith("a,b")
    assert data_equals("t.txt", "hi").type == "data_equals"
    assert command_exit("echo hi", expect_code=0).params["expect_code"] == 0
    assert tests_pass("tests/").params["path"] == "tests/"
    assert git_diff(max_changed_files=1).params == {"max_changed_files": 1}
    assert ast_check("m.py", defines=["f"]).params["defines"] == ["f"]
    assert api_state("user.state", "active").type == "api_state"
    assert custom("my_scorer", {"x": 1}).params == {"x": 1}


def test_assertions_list_requires_items() -> None:
    with pytest.raises(ValueError):
        assertions()


def test_dsl_task_runs_and_scores_end_to_end(tmp_path) -> None:
    """A task authored with the DSL passes validation and scores deterministically."""
    from tooltrace.runners.runner import TaskRunner

    task = TaskDefinition.model_validate(
        {
            "id": "dsl-pack/dsl-task",
            "version": "1.0.0",
            "category": "file-editing",
            "difficulty": "easy",
            "tags": [],
            "objective": "Write BAR into notes.txt.",
            "starting_workspace": {"notes.txt": "value=FOO"},
            "allowed_tools": ["write_file"],
            "assertions": [
                a.model_dump()
                for a in assertions(
                    file_contains("notes.txt", text="BAR"),
                    file_not_contains("notes.txt", text="FOO"),
                    data_equals("notes.txt", "value=BAR"),
                )
            ],
            "timeout_seconds": 30,
            "max_steps": 8,
            "network_policy": "disabled",
        }
    )
    runner = TaskRunner(output_dir=tmp_path)
    result, _events, _diff = runner.run(
        task,
        "scripted",
        {"script": [{"tool": "write_file", "args": {"path": "notes.txt", "content": "value=BAR"}}]},
    )
    assert result.success, f"{result.failure_reason}: {result.failure_detail}"
    component_keys = set(result.score.components)
    for scorer in ("file_contains", "file_not_contains", "data_equals"):
        # duplicate scorers get a "#N" suffix; match on the base name
        assert any(k == scorer or k.startswith(scorer + "#") for k in component_keys), (
            f"{scorer} missing from {component_keys}"
        )


def test_failing_dsl_task_scores_zero_on_mismatch(tmp_path) -> None:
    from tooltrace.runners.runner import TaskRunner

    task = TaskDefinition.model_validate(
        {
            "id": "dsl-pack/dsl-fail",
            "version": "1.0.0",
            "category": "file-editing",
            "difficulty": "easy",
            "tags": [],
            "objective": "Write BAR.",
            "allowed_tools": ["write_file"],
            "assertions": [file_contains("notes.txt", text="BAR").model_dump()],
            "timeout_seconds": 30,
            "max_steps": 4,
            "network_policy": "disabled",
        }
    )
    runner = TaskRunner(output_dir=tmp_path)
    result, _events, _diff = runner.run(task, "scripted", {"script": []})
    assert not result.success
