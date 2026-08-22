"""Model validation, task schema validation, and pack loading."""

from __future__ import annotations

import pytest
from tests.conftest import make_task
from tooltrace.core.exceptions import TaskValidationError
from tooltrace.core.models import FailureReason, TaskDefinition, TrustState
from tooltrace.tasks.loader import load_all_tasks, validate_task_document


def test_task_roundtrip(task: TaskDefinition) -> None:
    doc = task.model_dump(mode="json")
    assert TaskDefinition.model_validate(doc) == task


def test_invalid_id_rejected() -> None:
    with pytest.raises(ValueError):  # pydantic wraps as ValidationError (a ValueError)
        make_task(id="no-slash")


def test_assertions_required() -> None:
    with pytest.raises(ValueError):
        make_task(assertions=[])


def test_failure_taxonomy_has_12_categories() -> None:
    values = {f.value for f in FailureReason}
    expected = {
        "none",
        "planning",
        "tool_selection",
        "bad_arguments",
        "execution",
        "environment",
        "verification",
        "hallucinated_resource",
        "timeout",
        "loop",
        "context_loss",
        "destructive_edit",
        "policy_violation",
    }
    assert values == expected


def test_trust_states_ordered() -> None:
    assert [t.value for t in TrustState] == [
        "LOCAL",
        "COMMUNITY_VALIDATED",
        "REPRODUCED",
        "MAINTAINER_VERIFIED",
    ]


def test_builtin_packs_load() -> None:
    tasks = load_all_tasks()
    ids = {t.id for t in tasks}
    assert len(tasks) >= 12
    assert "file-editing/fix-config-typo" in ids
    assert "failure-recovery/retry-after-tool-failure" in ids


def test_validate_document_ok() -> None:
    errors = validate_task_document(make_task().model_dump(mode="json"))
    assert errors == []


def test_validate_document_bad() -> None:
    errors = validate_task_document({"id": "x/y"})
    assert errors  # missing required fields


def test_schema_validation_error_message() -> None:
    from tooltrace.tasks.loader import parse_task_document

    with pytest.raises(TaskValidationError):
        parse_task_document({"id": "a/b"}, "inline")
