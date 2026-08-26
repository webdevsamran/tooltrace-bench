"""pytest plugin integration: ToolTrace tasks as native pytest tests.

Runs real subprocess pytest sessions via ``pytester`` so the entry-point
plugin lifecycle is exercised exactly as users experience it.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

TASK_SPEC = """
from tooltrace.core.models import TaskDefinition

TASK = TaskDefinition.model_validate({
    "id": "plugin-pack/plugin-task",
    "version": "1.0.0",
    "category": "file-editing",
    "difficulty": "easy",
    "tags": [],
    "objective": "Replace FOO with BAR in notes.txt.",
    "starting_workspace": {"notes.txt": "value=FOO"},
    "allowed_tools": ["write_file"],
    "assertions": [
        {"type": "file_contains", "params": {"path": "notes.txt", "text": "BAR"},
         "weight": 1.0, "description": "BAR present"}
    ],
    "timeout_seconds": 30,
    "max_steps": 8,
    "network_policy": "disabled",
})
"""


def test_plugin_fixtures_run_task_and_pass(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        TASK_SPEC
        + """

def test_agent_edits_file(run_tooltrace, assert_tooltrace_pass):
    result, events, diff = run_tooltrace(
        TASK, "scripted",
        {"script": [{"tool": "write_file",
                     "args": {"path": "notes.txt", "content": "value=BAR"}}]},
    )
    assert_tooltrace_pass(result)
    assert any(e.type == "tool_result" for e in events)
    assert diff  # workspace changed
"""
    )
    result = pytester.runpytest("-q", "--no-header")
    out = result.stdout.str()
    assert result.ret == 0, f"expected pass, got ret={result.ret}:\n{out}"
    assert "1 passed" in out


def test_plugin_reports_failure_with_taxonomy_reason(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        TASK_SPEC
        + """

def test_agent_fails(run_tooltrace, assert_tooltrace_pass):
    result, _events, _diff = run_tooltrace(TASK, "scripted", {"script": []})
    assert_tooltrace_pass(result)  # must fail with the diagnostic message
"""
    )
    result = pytester.runpytest("-q", "--no-header", "--tb=long")
    out = result.stdout.str()
    assert result.ret != 0, "expected the inner test to fail"
    assert "1 failed" in out
    # diagnostic message carries the failure taxonomy reason and score
    assert "reason=verification" in out
    assert "score=0.000" in out


def test_marker_is_registered(pytester: pytest.Pytester) -> None:
    pytester.makepyfile(
        """
import pytest

@pytest.mark.tooltrace
def test_marked() -> None:
    assert True
"""
    )
    result = pytester.runpytest("-q", "--no-header", "-m", "tooltrace")
    result.assert_outcomes(passed=1)


def test_plugin_exports_expected_fixtures() -> None:
    """The plugin module itself exposes exactly the documented fixtures."""
    from tooltrace import pytest_plugin

    for name in ("tooltrace_runner", "run_tooltrace", "assert_tooltrace_pass"):
        assert hasattr(pytest_plugin, name)
