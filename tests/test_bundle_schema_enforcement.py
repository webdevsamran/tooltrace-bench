"""The published artifact schemas must actually gate artifacts.

`schemas/` has carried four documents since 0.1.0 and exactly one of them,
`task.schema.json`, was ever enforced. `result`, `trace` and `bundle-manifest`
were decorative: no runtime path, no test and no CI step ever validated an
artifact against them, so they were free to drift from the thing they claimed
to describe.

`docs/schemas-and-protocols.md` also states "New readers accept old artifacts
(forward compatibility is tested)". It was not. Every bundle test wrote a
bundle with the current code and read it straight back, which tests a round
trip, not compatibility with anything older. A frozen bundle is checked in here
so that sentence is true.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.artifacts.bundles import (
    load_bundle_result,
    load_bundle_task,
    load_bundle_trace,
    read_manifest,
    verify_bundle,
    write_bundle,
)
from tooltrace.artifacts.validation import (
    validate_bundle_artifacts,
    validate_manifest_document,
    validate_result_document,
    validate_trace_stream,
)
from tooltrace.core.exceptions import BundleError
from tooltrace.runners.runner import TaskRunner
from tooltrace.tasks import load_all_tasks

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"
_FROZEN = _ROOT / "tests" / "fixtures" / "bundles" / "v1-frozen.tooltrace"


def _write_real_bundle(out: Path) -> Path:
    task = next(t for t in load_all_tasks() if t.id == "file-editing/fix-config-typo")
    script = task.metadata.get("scripted_script")
    config = {"script": script} if isinstance(script, list) else None
    result, events, diff = TaskRunner().run(task, "scripted", config)
    return write_bundle(out, result, events, task, diff, {})


def test_a_freshly_written_bundle_validates(tmp_path: Path) -> None:
    bundle = _write_real_bundle(tmp_path)
    assert validate_bundle_artifacts(bundle) == []


def test_every_committed_bundle_validates() -> None:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles in results/")
    problems = {b.name: validate_bundle_artifacts(b) for b in bundles}
    assert {k: v for k, v in problems.items() if v} == {}


# --- non-vacuousness: a broken artifact has to be rejected -------------------


def test_an_invalid_failure_reason_is_rejected(tmp_path: Path) -> None:
    bundle = _write_real_bundle(tmp_path)
    path = bundle / "result.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["failure_reason"] = "not-a-real-reason"
    assert validate_result_document(doc), "an unknown failure_reason must not validate"


def test_a_manifest_missing_its_checksums_is_rejected() -> None:
    assert validate_manifest_document({"bundle_version": 1, "files": []})


def test_an_unknown_trace_event_type_is_rejected() -> None:
    problems = validate_trace_stream(
        [{"schema_version": 1, "timestamp": "2026-01-01T00:00:00Z", "seq": 1, "type": "nonsense"}]
    )
    assert problems


@pytest.mark.parametrize(
    ("seqs", "expected"),
    [
        ([1, 1, 2], "unique"),
        ([2, 1, 3], "monotonic"),
        ([2, 3, 4], "no gaps"),
    ],
)
def test_stream_invariants_a_schema_cannot_express(seqs: list[int], expected: str) -> None:
    """A per-line schema cannot constrain a stream, so these live in code."""
    events = [
        {"schema_version": 1, "timestamp": "2026-01-01T00:00:00Z", "seq": s, "type": "task_start"}
        for s in seqs
    ]
    problems = validate_trace_stream(events)
    assert any(expected in p for p in problems), problems


def test_write_bundle_refuses_to_ship_an_invalid_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "tooltrace.artifacts.validation.validate_bundle_artifacts",
        lambda _dir: ["result.json: synthetic problem"],
    )
    with pytest.raises(BundleError, match="does not match its published schemas"):
        _write_real_bundle(tmp_path)


def test_validation_can_be_switched_off(tmp_path: Path, monkeypatch) -> None:
    """The escape hatch exists for callers writing deliberately odd fixtures."""
    monkeypatch.setattr(
        "tooltrace.artifacts.validation.validate_bundle_artifacts",
        lambda _dir: ["result.json: synthetic problem"],
    )
    task = next(t for t in load_all_tasks() if t.id == "file-editing/fix-config-typo")
    script = task.metadata.get("scripted_script")
    result, events, diff = TaskRunner().run(task, "scripted", {"script": script})
    assert write_bundle(tmp_path, result, events, task, diff, {}, validate=False).is_dir()


# --- forward compatibility --------------------------------------------------


def test_todays_readers_accept_a_frozen_older_bundle() -> None:
    """This is what makes "forward compatibility is tested" a true sentence."""
    assert _FROZEN.is_dir(), "the frozen fixture bundle is missing"
    assert verify_bundle(_FROZEN) == []
    assert validate_bundle_artifacts(_FROZEN) == []

    manifest = read_manifest(_FROZEN)
    assert manifest["bundle_version"] == 1

    result = load_bundle_result(_FROZEN)
    assert result.task_id == "file-editing/fix-config-typo"

    task = load_bundle_task(_FROZEN)
    assert task.id == result.task_id

    events = load_bundle_trace(_FROZEN)
    assert [e.seq for e in events] == list(range(1, len(events) + 1))
