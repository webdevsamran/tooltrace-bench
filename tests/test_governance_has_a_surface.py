"""Dataset governance had to be reachable, and wiring it up found a defect.

`tooltrace/tasks/governance.py` implements provenance manifests with integrity
hashes, versioned pack indexes with semver compatibility ranges, cross-pack
fingerprint deduplication and a contamination-risk assessor. Seven of its public
functions had no caller outside their own tests, so an auditor asking "where did
this data come from, and could the model have seen it already" could be answered
by the package and not by the tool.

The defect the unreachability was hiding is the first section below.
`build_provenance_manifest` hashed `task.fixtures`. All 44 shipping tasks keep
their content in `starting_workspace` and leave `fixtures` empty, so every
manifest it could have produced covered **zero files** -- and
`verify_provenance_manifest` then reported that manifest as verified, because a
list with nothing in it has nothing to mismatch. A provenance document that
proves nothing about the data it is attached to is worse than none: it is the
artifact a reviewer stops at.

The second half of that defect is subtler and is checked here too. Verification
compared the manifest's entries against the task and never the other way round,
so content **added** after the manifest was written passed as verified.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tooltrace.cli.main import main
from tooltrace.tasks import load_all_tasks
from tooltrace.tasks.governance import (
    ProvenanceManifest,
    build_pack_index,
    build_provenance_manifest,
    find_duplicates,
    parse_range,
    satisfies_range,
    verify_provenance_manifest,
)

TASK_ID = "security/memory-poisoning"


@pytest.fixture(scope="module")
def tasks() -> list:
    return load_all_tasks()


@pytest.fixture(scope="module")
def task(tasks: list):
    return next(t for t in tasks if str(t.id) == TASK_ID)


# --- the defect wiring it up exposed -----------------------------------------


def test_a_manifest_covers_the_content_the_task_actually_carries(task) -> None:
    """Not `fixtures`, which every shipping task leaves empty."""
    workspace = dict(getattr(task, "starting_workspace", {}) or {})
    assert workspace, "this task no longer carries workspace content; pick another"

    manifest = build_provenance_manifest(task)
    covered = {fp.path for fp in manifest.fixtures}
    assert covered >= set(workspace), "the manifest does not cover the starting workspace"


def test_no_shipping_task_would_get_an_empty_manifest(tasks: list) -> None:
    """The whole corpus, because one task passing proves one task."""
    empty = [
        str(t.id)
        for t in tasks
        if (getattr(t, "starting_workspace", None) or getattr(t, "fixtures", None))
        and not build_provenance_manifest(t).fixtures
    ]
    assert empty == [], f"these tasks have content but get an empty manifest: {empty}"


def test_content_added_after_the_manifest_is_not_silently_verified(task) -> None:
    """Checking only the manifest's own entries lets new content through."""
    manifest = build_provenance_manifest(task)
    assert verify_provenance_manifest(manifest, task) == []

    extra = task.model_copy(deep=True)
    extra.starting_workspace = {**extra.starting_workspace, "planted.txt": "new, unvouched-for"}
    problems = verify_provenance_manifest(manifest, extra)
    assert any("not covered by the manifest" in p for p in problems), problems


def test_edited_content_is_caught(task) -> None:
    manifest = build_provenance_manifest(task)
    path = sorted(task.starting_workspace)[0]
    edited = task.model_copy(deep=True)
    edited.starting_workspace = {**edited.starting_workspace, path: "tampered"}
    assert any("content hash mismatch" in p for p in verify_provenance_manifest(manifest, edited))


def test_removed_content_is_caught(task) -> None:
    manifest = build_provenance_manifest(task)
    path = sorted(task.starting_workspace)[0]
    shrunk = task.model_copy(deep=True)
    shrunk.starting_workspace = {k: v for k, v in shrunk.starting_workspace.items() if k != path}
    assert any("missing from task" in p for p in verify_provenance_manifest(manifest, shrunk))


def test_an_edited_manifest_is_caught(task) -> None:
    """Otherwise the checksum is decoration."""
    manifest = build_provenance_manifest(task)
    manifest.task_version = "9.9.9"
    assert any("manifest was modified" in p for p in verify_provenance_manifest(manifest, task))


def test_the_two_content_mappings_stay_distinguishable() -> None:
    """A path can legitimately appear in both; merging would lose one."""

    class Fake:
        def __init__(self) -> None:
            self.id = "demo/collision"
            self.version = "1.0.0"
            self.fixtures = {"config.json": "from fixtures"}
            self.starting_workspace = {"config.json": "from the workspace"}

        def model_dump(self, mode: str = "json") -> dict:
            return {"id": self.id}

    manifest = build_provenance_manifest(Fake())
    kinds = {fp.kind for fp in manifest.fixtures}
    assert kinds == {"fixtures", "starting_workspace"}
    assert len({fp.sha256 for fp in manifest.fixtures}) == 2


# --- the CLI surface ----------------------------------------------------------


def test_provenance_round_trips_through_the_cli(tmp_path: Path, capsys) -> None:
    out = tmp_path / "manifests"
    assert main(["govern", "provenance", "--task", TASK_ID, "--out", str(out)]) == 0
    capsys.readouterr()

    written = sorted(out.glob("*.provenance.json"))
    assert len(written) == 1
    manifest = ProvenanceManifest.model_validate_json(written[0].read_text(encoding="utf-8"))
    assert manifest.task_id == TASK_ID
    assert manifest.fixtures, "the written manifest covers nothing"

    assert main(["govern", "provenance", "--verify", str(written[0]), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verified"] is True
    assert payload["files_covered"] == len(manifest.fixtures)


def test_verifying_a_tampered_manifest_exits_nonzero(tmp_path: Path, capsys) -> None:
    out = tmp_path / "m"
    main(["govern", "provenance", "--task", TASK_ID, "--out", str(out)])
    capsys.readouterr()
    path = next(out.glob("*.provenance.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["fixtures"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")

    assert main(["govern", "provenance", "--verify", str(path), "--json"]) != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verified"] is False
    assert payload["problems"]


def test_a_manifest_for_an_uninstalled_task_is_refused(tmp_path: Path, capsys) -> None:
    path = tmp_path / "foreign.json"
    path.write_text(
        json.dumps(
            {
                "task_id": "nowhere/at-all",
                "task_version": "1.0.0",
                "task_sha256": "0" * 64,
                "fixtures": [],
            }
        ),
        encoding="utf-8",
    )
    assert main(["govern", "provenance", "--verify", str(path)]) != 0
    assert "not installed" in capsys.readouterr().err


def test_the_index_reports_a_range_it_does_not_satisfy(capsys) -> None:
    """Versioning an index is pointless if nothing ever checks the version."""
    assert main(["govern", "index", "--pack", "security", "--requires", ">=1.0.0"]) == 0
    capsys.readouterr()
    assert main(["govern", "index", "--pack", "security", "--requires", ">=2.0.0"]) != 0
    assert "INCOMPATIBLE" in capsys.readouterr().out


def test_the_index_covers_only_its_own_pack(capsys) -> None:
    assert main(["govern", "index", "--pack", "security", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["pack"] == "security"
    assert rows[0]["tasks"] > 0
    assert rows[0]["index_sha256"]


def test_an_unknown_pack_is_refused(capsys) -> None:
    assert main(["govern", "index", "--pack", "no-such-pack"]) != 0
    assert "no such pack" in capsys.readouterr().err


def test_the_shipped_corpus_has_no_duplicate_tasks(capsys) -> None:
    """Two tasks with one fingerprint measure the same thing twice."""
    assert main(["govern", "duplicates", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scanned"] > 0
    assert payload["duplicate_groups"] == []


def test_duplicate_detection_is_not_vacuous(task) -> None:
    """The test above passes trivially if the detector never fires."""
    twin = task.model_copy(deep=True)
    twin.id = "demo/copy-of-the-above"
    groups = find_duplicates([task, twin])
    assert len(groups) == 1
    assert set(groups[0]) == {str(task.id), "demo/copy-of-the-above"}


def test_contamination_reports_signals_and_says_what_it_cannot_prove(capsys) -> None:
    assert main(["govern", "contamination", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tasks"]
    assert {r["assessed"] for r in payload["tasks"]} <= {"none", "low", "medium", "high"}

    assert main(["govern", "contamination"]) == 0
    out = capsys.readouterr().out
    assert "not proof" in out


def test_a_declaration_below_the_evidence_fails(tasks: list, capsys, monkeypatch) -> None:
    """The only direction that makes the benchmark look better than it is."""
    flagged = next(
        t
        for t in tasks
        if "readme.md" in {p.lower() for p in (getattr(t, "starting_workspace", {}) or {})}
    )
    patched = flagged.model_copy(deep=True)
    patched.metadata = {**patched.metadata, "contamination_risk": {"level": "none"}}
    others = [t for t in tasks if str(t.id) != str(flagged.id)]
    monkeypatch.setattr("tooltrace.tasks.load_all_tasks", lambda *a, **k: [patched, *others])

    assert main(["govern", "contamination", "--json"]) != 0
    payload = json.loads(capsys.readouterr().out)
    assert str(flagged.id) in payload["understated"]


# --- the helpers the CLI relies on -------------------------------------------


@pytest.mark.parametrize(
    ("version", "spec", "expected"),
    [
        ("1.0.0", ">=1.0.0", True),
        ("1.0.0", ">=1.1.0", False),
        ("1.1.0", ">=1.0.0,<=1.2.0", True),
        ("1.3.0", ">=1.0.0,<=1.2.0", False),
        ("1.0.0", "==1.0.0", True),
        # Deliberately unsupported, and deliberately False rather than a guess.
        ("1.2.0", "^1.0.0", False),
        ("1.0.0", "1.0.0", False),
        ("not-a-version", ">=1.0.0", False),
    ],
)
def test_satisfies_range(version: str, spec: str, expected: bool) -> None:
    assert satisfies_range(version, spec) is expected


def test_an_unreadable_range_is_distinguishable_from_an_unsatisfied_one() -> None:
    """Both answer False; only one of them is the user's fault.

    Telling somebody their pack is incompatible when `^1.0.0` was never parsed
    sends them looking for a version problem that does not exist.
    """
    assert parse_range(">=1.0.0") is not None
    assert parse_range("^1.0.0") is None
    assert parse_range("1.0.0") is None


def test_the_cli_says_so_rather_than_reporting_incompatible(capsys) -> None:
    assert main(["govern", "index", "--pack", "security", "--requires", "^1.0.0"]) != 0
    err = capsys.readouterr().err
    assert "not a range this understands" in err
    assert ">=X.Y.Z" in err


def test_an_index_changes_when_a_task_does(tasks: list) -> None:
    """Otherwise the checksum cannot be used to detect a changed pack."""
    pack = [t for t in tasks if str(t.id).startswith("security/")]
    before = build_pack_index("security", pack).index_sha256
    edited = [t.model_copy(deep=True) for t in pack]
    edited[0].objective = edited[0].objective + " (changed)"
    assert build_pack_index("security", edited).index_sha256 != before
