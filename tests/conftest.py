"""Shared fixtures: a minimal valid task and a temp workspace."""

from __future__ import annotations

from pathlib import Path

import pytest
from tooltrace.core.models import TaskDefinition


def make_task(**overrides) -> TaskDefinition:
    doc: dict = {
        "id": "test-pack/demo-task",
        "name": "demo",
        "version": "1.0.0",
        "category": "file-editing",
        "difficulty": "easy",
        "tags": [],
        "objective": "Replace FOO with BAR in notes.txt.",
        "description": "Edit the file.",
        "starting_workspace": {"notes.txt": "value=FOO"},
        "allowed_tools": ["read_file", "write_file", "patch_file"],
        "assertions": [
            {
                "type": "file_contains",
                "params": {"path": "notes.txt", "text": "BAR"},
                "weight": 1.0,
                "description": "BAR present",
            }
        ],
        "expected_artifacts": ["notes.txt"],
        "timeout_seconds": 30,
        "max_steps": 8,
        "network_policy": "disabled",
    }
    doc.update(overrides)
    return TaskDefinition.model_validate(doc)


@pytest.fixture
def task() -> TaskDefinition:
    return make_task()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "notes.txt").write_text("value=FOO", encoding="utf-8")
    return ws
