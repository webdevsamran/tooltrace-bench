"""Anti-gaming checks must inspect something, and must catch it.

`anti_gaming_checks` in `tooltrace/analysis/core.py` has shipped since 0.2.0 and
reads `assertion_results`, `declared_assertions`, `task_hashes`,
`harness_sha256` and `expected_harness_sha256` off the result it is given.
`EvalResult` has none of those fields, so on a real result it returned
`{"ok": True, "problems": []}` having performed zero checks.

Wiring that up directly would have been worse than leaving it unwired: a
permanently green integrity check is exactly the "CI step named for a validation
it never performed" that this repository has already had to correct once. So the
checks were rebuilt against data a bundle really contains, and each one is
tested here against an artifact that should fail it.

Distinguishing capability from benchmark gaming is one of the gaps the wider
field names most often. A check that cannot fail does not close it.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from tooltrace.analysis.core import anti_gaming_checks
from tooltrace.analysis.integrity import (
    check_bundle_integrity,
    declared_vs_scored,
    installed_task_for,
    leaked_expected_values,
    task_matches_published,
)
from tooltrace.artifacts.bundles import load_bundle_result
from tooltrace.cli.main import main

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"


def _a_bundle() -> Path:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    return bundles[0]


def test_the_original_function_cannot_see_a_real_result() -> None:
    """Documents why this module exists, so nobody re-wires the old path."""
    result = load_bundle_result(_a_bundle()).model_dump(mode="json")
    for field in ("assertion_results", "declared_assertions", "task_hashes", "harness_sha256"):
        assert field not in result, (
            f"EvalResult now has {field}; anti_gaming_checks may be wireable directly, "
            "and this module should be revisited"
        )
    assert anti_gaming_checks(result, {}) == {"ok": True, "problems": []}, (
        "it passes because it inspects nothing, which is the whole point of this test"
    )


# --- each check must catch its own defect -----------------------------------


def test_a_dropped_assertion_is_caught() -> None:
    """A run that silently skips a failing assertion scores more than it earned."""
    task = {
        "assertions": [
            {"type": "file_contains", "description": "a"},
            {"type": "x", "description": "b"},
        ]
    }
    scoring = {"score": {"components": {"a": 1.0}}}
    assert declared_vs_scored(task, scoring) == ["declared assertions absent from the score: ['b']"]


def test_a_fully_scored_task_is_clean() -> None:
    task = {"assertions": [{"type": "file_contains", "description": "a"}]}
    assert declared_vs_scored(task, {"score": {"components": {"a": 1.0}}}) == []


def test_a_modified_task_is_caught() -> None:
    published = {"assertions": [{"type": "a"}, {"type": "b"}], "starting_workspace": {"f": "x"}}
    trimmed = {"assertions": [{"type": "a"}], "starting_workspace": {"f": "x"}}
    problems = task_matches_published(trimmed, published)
    assert any("assertions differ" in p for p in problems)


def test_a_modified_fixture_is_caught() -> None:
    published = {"assertions": [], "starting_workspace": {"f": "original"}}
    edited = {"assertions": [], "starting_workspace": {"f": "made easier"}}
    problems = task_matches_published(edited, published)
    assert any("starting workspace differs" in p for p in problems)


def test_an_unmodified_task_is_clean() -> None:
    published = {"assertions": [{"type": "a"}], "starting_workspace": {"f": "x"}}
    assert task_matches_published(dict(published), published) == []


@pytest.mark.parametrize(
    "where",
    [
        {"objective": "Write DEPLOY_TOKEN_PLACEHOLDER into config.ini", "starting_workspace": {}},
        {"objective": "Fix it", "starting_workspace": {"hint.txt": "use DEPLOY_TOKEN_PLACEHOLDER"}},
    ],
)
def test_an_answer_visible_in_the_prompt_is_caught(where: dict) -> None:
    """If the task states the expected value, the score measures transcription."""
    task = {
        **where,
        "assertions": [{"type": "file_contains", "params": {"text": "DEPLOY_TOKEN_PLACEHOLDER"}}],
    }
    assert leaked_expected_values(task)


def test_a_task_that_hides_its_answer_is_clean() -> None:
    task = {
        "objective": "Fix the typo in notes.txt",
        "starting_workspace": {"notes.txt": "reday for launch"},
        "assertions": [{"type": "file_contains", "params": {"text": "ready for launch"}}],
    }
    assert leaked_expected_values(task) == []


def test_a_not_contains_assertion_is_exempt() -> None:
    """Asserting a string is *absent* requires it to be present to begin with."""
    task = {
        "objective": "Remove the placeholder",
        "starting_workspace": {"a.txt": "DEPLOY_TOKEN_PLACEHOLDER"},
        "assertions": [
            {"type": "file_not_contains", "params": {"text": "DEPLOY_TOKEN_PLACEHOLDER"}}
        ],
    }
    assert leaked_expected_values(task) == []


def test_a_short_generic_value_is_not_treated_as_a_leak() -> None:
    """A checker that cries wolf on `ok` appearing in a prompt gets ignored."""
    task = {
        "objective": "write ok",
        "starting_workspace": {},
        "assertions": [{"type": "file_contains", "params": {"text": "ok"}}],
    }
    assert leaked_expected_values(task) == []


# --- end to end -------------------------------------------------------------


def test_every_committed_bundle_passes_its_own_integrity_checks() -> None:
    for bundle in sorted(_RESULTS.glob("*.tooltrace")):
        result = load_bundle_result(bundle)
        report = check_bundle_integrity(bundle, installed_task_for(result.task_id))
        assert report["ok"], f"{bundle.name}: {report['problems']}"


def test_a_tampered_bundle_fails_end_to_end(tmp_path: Path) -> None:
    source = _a_bundle()
    tampered = tmp_path / "b.tooltrace"
    shutil.copytree(source, tampered)
    task = yaml.safe_load((tampered / "task.yaml").read_text(encoding="utf-8"))
    task["assertions"] = task["assertions"][:1]
    (tampered / "task.yaml").write_text(yaml.safe_dump(task), encoding="utf-8")

    report = check_bundle_integrity(tampered, installed_task_for(task["id"]))
    assert report["ok"] is False
    assert any("differ from the published task" in p for p in report["problems"])


def test_verify_reports_integrity_alongside_checksums(capsys) -> None:
    assert main(["verify", str(_a_bundle()), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["integrity_ok"] is True
    assert [c for c in payload["integrity"]["checks_run"] if c], "no checks were run"


def test_verify_states_that_the_harness_hash_is_not_checked(capsys) -> None:
    """An unperformed check must not read as a passed one."""
    main(["verify", str(_a_bundle()), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["integrity"]["harness_hash_recorded"] is False


def test_integrity_can_be_skipped(capsys) -> None:
    main(["verify", str(_a_bundle()), "--no-integrity", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["integrity"]["skipped"] is True
