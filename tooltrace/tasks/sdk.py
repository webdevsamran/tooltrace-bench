"""Task authoring SDK: scaffold, validate and test task packs without
touching core internals.

Python API:

    from tooltrace.tasks.sdk import scaffold_task, validate_task_dir, test_task

CLI equivalents: ``tooltrace task scaffold|validate|test``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

from tooltrace.core.exceptions import TaskValidationError
from tooltrace.core.models import TaskDefinition
from tooltrace.tasks.loader import load_pack, validate_task_document

SCAFFOLD_TEMPLATE: dict[str, object] = {
    "id": "my-pack/my-task",
    "name": "My Task",
    "version": "1.0.0",
    "category": "file-editing",
    "difficulty": "easy",
    "tags": ["example"],
    "objective": "Describe what the agent must accomplish.",
    "description": "Longer, unambiguous instructions.",
    "starting_workspace": {"notes.txt": "hello world"},
    "allowed_tools": ["read_file", "write_file", "patch_file"],
    "assertions": [
        {
            "type": "file_contains",
            "params": {"path": "notes.txt", "text": "hello"},
            "weight": 1.0,
            "description": "greeting preserved",
        }
    ],
    "expected_artifacts": ["notes.txt"],
    "timeout_seconds": 60,
    "max_steps": 8,
    "network_policy": "disabled",
}


def scaffold_task(pack_dir: Path, task_id: str) -> Path:
    """Write a ready-to-edit scaffold YAML into *pack_dir*."""
    doc = dict(SCAFFOLD_TEMPLATE)
    doc["id"] = task_id
    slug = task_id.split("/")[-1]
    pack_dir.mkdir(parents=True, exist_ok=True)
    target = pack_dir / f"{slug}.yaml"
    if target.exists():
        raise TaskValidationError(f"refusing to overwrite existing task file: {target}")
    target.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return target


def validate_task_dir(path: Path) -> tuple[list[TaskDefinition], list[str]]:
    """Validate every task document under *path* (file or directory).

    Returns (valid_tasks, error_strings). Never raises for invalid documents.
    """
    tasks: list[TaskDefinition] = []
    errors: list[str] = []
    files = (
        sorted([path])
        if path.is_file()
        else sorted(list(path.rglob("*.yaml")) + list(path.rglob("*.yml")))
    )
    if not files:
        errors.append(f"no task files found under {path}")
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
            doc = yaml.safe_load(text)
            problems = validate_task_document(doc)
            if problems:
                errors.append(f"{f}: " + "; ".join(problems[:5]))
                continue
            tasks.append(TaskDefinition.model_validate(doc))
        except Exception as exc:
            errors.append(f"{f}: {exc}")
    return tasks, errors


def test_task(task: TaskDefinition) -> list[str]:
    """Smoke-test a task deterministically:

    1. materialize the starting workspace;
    2. verify all assertion-referenced paths exist or are creatable;
    3. run the scripted reference solution (if provided in
       ``metadata.scripted_script``) through the real runner;
    4. confirm the reference solution passes every assertion.
    """
    problems: list[str] = []
    script = task.metadata.get("scripted_script")
    if not isinstance(script, list):
        problems.append(
            "metadata.scripted_script missing — add a reference solution so "
            "`task test` can verify the task is solvable"
        )
        return problems

    from tooltrace.runners.runner import TaskRunner

    runner = TaskRunner()
    result, _events, _diff = runner.run(
        task,
        agent_name="scripted",
        agent_config={"script": script},
        run_id="task-test",
    )
    if not result.success:
        problems.append(
            f"reference solution did not pass (score={result.score.total}, "
            f"failure={result.failure_reason.value})"
        )
    return problems


def test_pack(pack_dir: Path) -> tuple[int, list[str]]:
    """Test every task in a pack. Returns (passed_count, problems)."""
    tasks = load_pack(pack_dir)
    passed = 0
    problems: list[str] = []
    for t in tasks:
        errs = test_task(t)
        if errs:
            problems.extend(f"{t.id}: {e}" for e in errs)
        else:
            passed += 1
    return passed, problems


def roundtrip_check(task: TaskDefinition) -> bool:
    """Serialization round-trip: model → yaml → model equality."""
    doc = yaml.safe_load(yaml.safe_dump(task.model_dump(mode="json")))
    return TaskDefinition.model_validate(doc) == task


def scratch_workspace(task: TaskDefinition) -> Path:
    """Materialize a task's starting workspace in a temp dir (for authors)."""
    tmp = Path(tempfile.mkdtemp(prefix="tooltrace-author-"))
    for rel, content in task.starting_workspace.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp
