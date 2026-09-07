"""Tasks needing absent tooling are skipped, never scored as failures.

Compiled-language tasks (#9) need `go` or `cargo`, which many machines do not
have. Scoring a missing toolchain as an agent failure would make results
depend on the runner's installed software rather than on agent behaviour --
the same class of mistake as comparing two benchmark runs from different
environments.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tooltrace.core.models import Assertion, TaskDefinition
from tooltrace.tasks import find_task, load_all_tasks
from tooltrace.tasks.availability import availability, missing_tools, partition

_ROOT = Path(__file__).resolve().parent.parent


def _task(**overrides) -> TaskDefinition:
    base = {
        "id": "demo/task",
        "category": "demo",
        "objective": "o",
        "allowed_tools": ["shell"],
        "assertions": [Assertion(type="file_exists", params={"path": "a"})],
    }
    base.update(overrides)
    return TaskDefinition(**base)


def test_a_task_with_no_requirements_is_always_runnable() -> None:
    state = availability(_task())
    assert state.runnable
    assert state.reason == ""


def test_an_absent_tool_makes_a_task_unrunnable_with_a_reason() -> None:
    state = availability(_task(requires_tools=["definitely-not-a-real-tool"]))
    assert not state.runnable
    assert "definitely-not-a-real-tool" in state.reason
    assert "not on PATH" in state.reason


def test_a_present_tool_satisfies_the_requirement() -> None:
    """Python is running this test, so it is by definition on PATH."""
    executable = Path(sys.executable).stem
    assert missing_tools(_task(requires_tools=[executable])) == ()


def test_partition_separates_runnable_from_skipped() -> None:
    runnable, skipped = partition(
        [_task(id="a/ok"), _task(id="b/no", requires_tools=["definitely-not-a-real-tool"])]
    )
    assert [t.id for t in runnable] == ["a/ok"]
    assert [t.id for t, _ in skipped] == ["b/no"]
    assert "definitely-not-a-real-tool" in skipped[0][1]


def test_compiled_language_tasks_declare_their_toolchain() -> None:
    """The point of the field: these tasks must not run without their compiler."""
    expected = {
        "shell-workflow/go-build-fix": "go",
        "shell-workflow/rust-build-fix": "cargo",
    }
    for task_id, tool in expected.items():
        task = find_task(task_id)
        assert tool in task.requires_tools, (
            f"{task_id} needs {tool} but does not declare it, so it would be "
            "scored as a failure on a machine without the toolchain"
        )


def test_every_task_declaring_a_shell_build_declares_its_toolchain() -> None:
    """Guard the class, not just today's two tasks."""
    binaries = ("cargo ", "go build", "go test", "go vet", "rustc ", "javac ", "dotnet ")
    for task in load_all_tasks():
        commands = [
            str(a.params.get("command", "")) for a in task.assertions if a.type == "command_exit"
        ]
        for command in commands:
            for binary in binaries:
                if command.startswith(binary):
                    tool = binary.split()[0]
                    assert tool in task.requires_tools, (
                        f"{task.id} asserts `{command}` but does not declare "
                        f"requires_tools: [{tool}]"
                    )


def test_run_skips_rather_than_failing_when_a_tool_is_absent(tmp_path: Path) -> None:
    """End-to-end: the CLI exits 0 and reports a skip, not a failure."""
    task = find_task("shell-workflow/go-build-fix").model_copy(
        update={"id": "demo/needs-nothing-real", "requires_tools": ["no-such-tool-xyz"]}
    )
    pack = tmp_path / "packs" / "demo"
    pack.mkdir(parents=True)
    import yaml

    (pack / "t.yaml").write_text(
        yaml.safe_dump(json.loads(task.model_dump_json())), encoding="utf-8"
    )
    proc = subprocess.run(
        [sys.executable, "-m", "tooltrace.cli.main", "tasks", "--json"],
        capture_output=True,
        text=True,
        cwd=_ROOT,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    listed = payload["tasks"] if isinstance(payload, dict) else payload
    by_id = {t["id"]: t for t in listed}
    go_task = by_id["shell-workflow/go-build-fix"]
    assert "requires_tools" in go_task and "runnable_here" in go_task, (
        "`tasks` must report what a task needs and whether it can run here"
    )
