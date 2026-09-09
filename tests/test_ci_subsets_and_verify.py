"""Cheap CI subsets, and a bundle check with a name people will look for.

Two small gaps that block adoption rather than capability.

Nobody runs a full benchmark on every pull request. Without `--limit` there was
no way to trim one, so the CI integration this project is built for could not
actually be set up. The risk in adding it is that a truncated run reads like a
full one, so the selection is recorded — policy, seed, how many of how many, and
the exact ids — and announced on stderr.

Bundle verification existed but had no verb. It lived under
`reproduce --no-rerun`, a command documented as "verify and re-run", so the
cheap read-only check was reachable only by asking the expensive one not to do
its main job. Third-party auditing is the entire point of a checksummed bundle.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tooltrace.cli.main import main

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"


def _benchmark(capsys, *extra: str) -> dict:
    code = main(["benchmark", "--agent", "scripted", "--runs", "1", "--json", *extra])
    assert code == 0
    return json.loads(capsys.readouterr().out)


# --- subsets ---------------------------------------------------------------


def test_a_full_run_is_not_marked_as_a_subset(capsys) -> None:
    payload = _benchmark(capsys, "--task", "file-editing/fix-config-typo")
    selection = payload["selection"]
    assert selection["is_subset"] is False
    assert selection["policy"] == "all"
    assert selection["selected"] == selection["available"] == 1


def test_limit_records_the_subset_it_ran(capsys) -> None:
    payload = _benchmark(capsys, "--limit", "2")
    selection = payload["selection"]
    assert selection["selected"] == 2
    assert selection["available"] > 2
    assert selection["is_subset"] is True
    assert len(selection["task_ids"]) == 2


def test_limit_without_shuffle_is_stable(capsys) -> None:
    """Deterministic by default: the same N tasks every time, sorted by id."""
    first = _benchmark(capsys, "--limit", "3")["selection"]
    second = _benchmark(capsys, "--limit", "3")["selection"]
    assert first["task_ids"] == second["task_ids"]
    assert first["task_ids"] == sorted(first["task_ids"])
    assert first["policy"] == "first_by_id"


def test_the_same_seed_selects_the_same_tasks(capsys) -> None:
    first = _benchmark(capsys, "--limit", "3", "--shuffle", "--seed", "42")["selection"]
    second = _benchmark(capsys, "--limit", "3", "--shuffle", "--seed", "42")["selection"]
    assert first["task_ids"] == second["task_ids"]
    assert first["policy"] == "seeded_shuffle"
    assert first["seed"] == 42


def test_a_different_seed_selects_differently(capsys) -> None:
    """Otherwise --shuffle is decoration and the subset is always the same N."""
    a = _benchmark(capsys, "--limit", "3", "--shuffle", "--seed", "1")["selection"]
    b = _benchmark(capsys, "--limit", "3", "--shuffle", "--seed", "999")["selection"]
    assert a["task_ids"] != b["task_ids"]


def test_a_subset_announces_itself(capsys) -> None:
    """A truncated run must never be mistaken for a full one."""
    main(["benchmark", "--agent", "scripted", "--runs", "1", "--limit", "2", "--json"])
    assert "running 2 of" in capsys.readouterr().err


def test_a_limit_larger_than_the_suite_is_not_a_subset(capsys) -> None:
    payload = _benchmark(capsys, "--limit", "9999")
    assert payload["selection"]["is_subset"] is False


def test_showdown_can_be_trimmed_too(capsys) -> None:
    code = main(["showdown", "--agents", "scripted", "--runs", "1", "--limit", "2", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selection"]["selected"] == 2


# --- verify ----------------------------------------------------------------


def _a_bundle() -> Path:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    return bundles[0]


def test_verify_accepts_an_intact_bundle(capsys) -> None:
    code = main(["verify", str(_a_bundle()), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["checksums_ok"] and payload["schema_ok"]
    assert payload["compatibility_key"]


def test_verify_detects_tampering(tmp_path: Path, capsys) -> None:
    """A checksum that catches nothing is indistinguishable from no checksum."""
    tampered = tmp_path / "tampered.tooltrace"
    shutil.copytree(_a_bundle(), tampered)
    (tampered / "result.json").write_text("{}", encoding="utf-8")

    code = main(["verify", str(tampered), "--json"])
    assert code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["checksums_ok"] is False
    assert any("result.json" in p for p in payload["checksum_problems"])


def test_checksums_and_schemas_are_reported_separately(tmp_path: Path, capsys) -> None:
    """They fail for different reasons: tampering versus never having conformed."""
    tampered = tmp_path / "b.tooltrace"
    shutil.copytree(_a_bundle(), tampered)
    (tampered / "result.json").write_text("{}", encoding="utf-8")

    main(["verify", str(tampered), "--no-schema", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["checksums_ok"] is False
    assert payload["schema_ok"] is True, "--no-schema must skip schema validation"
    assert payload["schema_problems"] == []


def test_verify_reports_a_missing_bundle_rather_than_crashing(tmp_path: Path, capsys) -> None:
    code = main(["verify", str(tmp_path / "nope.tooltrace"), "--json"])
    assert code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["problems"]
