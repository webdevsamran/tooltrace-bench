"""pytest integration: run ToolTrace tasks as native pytest tests.

Enabled automatically once ``tooltrace-bench`` is installed (entry point
group ``pytest11``); it only adds fixtures and a marker — nothing else in
your suite changes. This is the CI-gate path for teams that already live in
pytest (mirrors how DeepEval integrates, but for full agent trajectories):

    def test_agent_edits_file(run_tooltrace, assert_tooltrace_pass):
        task = load_my_task("fileops/demo-new-task")
        result, events, diff = run_tooltrace(
            task, "scripted", {"script": [{"tool": "write_file",
                                           "args": {"path": "notes.txt",
                                                    "content": "value=BAR"}}]}
        )
        assert_tooltrace_pass(result)
        assert any(e.type == "tool_result" for e in events)

Fixtures:
- ``tooltrace_runner`` — session-scoped :class:`TaskRunner` with an isolated
  output directory.
- ``run_tooltrace(task, agent_name="scripted", agent_config=None)`` — factory
  returning ``(EvalResult, list[TraceEvent], workspace_diff_text)``.
- ``assert_tooltrace_pass(result)`` — asserts success with a diagnostic
  message carrying failure reason, detail and score.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tooltrace.core.models import EvalResult, TaskDefinition, TraceEvent


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "tooltrace: agent-evaluation test backed by the ToolTrace harness"
    )


@pytest.fixture(scope="session")
def tooltrace_runner(tmp_path_factory: pytest.TempPathFactory) -> object:
    from tooltrace.runners.runner import TaskRunner

    out: Path = tmp_path_factory.mktemp("tooltrace-runs")
    return TaskRunner(output_dir=out)


@pytest.fixture
def run_tooltrace(
    tooltrace_runner: object,
) -> Callable[..., tuple[EvalResult, list[TraceEvent], str]]:
    from tooltrace.runners.runner import TaskRunner

    runner: TaskRunner = tooltrace_runner  # type: ignore[assignment]

    def _run(
        task: TaskDefinition,
        agent_name: str = "scripted",
        agent_config: dict[str, object] | None = None,
    ) -> tuple[EvalResult, list[TraceEvent], str]:
        return runner.run(task, agent_name, agent_config)

    return _run


@pytest.fixture
def assert_tooltrace_pass() -> Callable[[EvalResult], None]:
    def _check(result: EvalResult) -> None:
        assert result.success, (
            f"task {result.task_id} failed: reason={result.failure_reason} "
            f"detail={result.failure_detail!r} score={result.score.total:.3f}"
        )

    return _check
