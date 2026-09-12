"""The trust ladder, and what it takes to climb it.

`TrustState` declares four levels with a docstring promising they are "never
implied without evidence". Every bundle this project has written is `LOCAL`, and
`promote_trust` had no caller outside the test suite — so the upper three were
labels nothing could produce. That is worse than three levels honestly held: a
reader who sees four states reasonably assumes some bundle is in one of them.

The load-bearing rule is the first test below. **A bundle re-run on the machine
that produced it is not independently reproduced.** It demonstrates that the
machine is deterministic, which is a real but much weaker claim, and conflating
the two would make `REPRODUCED` mean nothing at all.

That rule got the wrong answer on its first run: `build_attestation` assembled a
hardware profile by hand with empty `os` and `machine`, so every attestation
differed from every bundle and a same-machine re-run was reported as independent
reproduction — inverting the one thing this module exists to enforce.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from tooltrace.analysis.attestation import (
    DIFFERENT_MACHINE,
    SAME_MACHINE,
    SCHEMA,
    UNKNOWN_MACHINE,
    build_attestation,
    machine_relation,
    manifest_digest,
    promotion_for,
    render_markdown,
    verify_attestation,
)
from tooltrace.cli.main import main
from tooltrace.core.models import TrustState

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"

ELSEWHERE = {
    "os": "Linux",
    "machine": "aarch64",
    "cpu_count": 64,
    "memory_gb": 256.0,
    "gpu_names": ["NVIDIA H100"],
    "backend": "vllm",
}


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    """A bundle produced *by this machine*, not copied from the repository.

    It used to copy a committed bundle out of `results/`, which made the
    load-bearing test below assert that the hardware profile recorded in a file
    somebody else generated matched the profile of whoever is running the suite.
    That is only true on the machine the fixtures were last regenerated on: the
    moment they were regenerated on Windows, `machine_relation` correctly
    answered `different_machine` on every Linux and macOS runner and the test
    failed everywhere but here.

    The test is about same-machine versus independent reproduction, so the
    bundle has to come from the machine running it. Generating it does exactly
    that and costs one scripted run.
    """
    from tooltrace.artifacts.bundles import write_bundle
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks import load_all_tasks

    task = next(t for t in load_all_tasks() if t.id == "file-editing/fix-config-typo")
    script = task.metadata.get("scripted_script")
    config = {"script": script} if isinstance(script, list) else None
    result, events, diff = TaskRunner().run(task, "scripted", config)
    return write_bundle(tmp_path, result, events, task, diff, {})


def attest(bundle: Path, **over) -> dict:
    kwargs = {
        "attester": "alice@example.test",
        "attested_at": "2026-09-09T00:00:00+00:00",
        "reproduced": True,
    }
    kwargs.update(over)
    return build_attestation(bundle, **kwargs)


# --- the rule the feature rests on ------------------------------------------


def test_reproducing_on_your_own_machine_does_not_promote(bundle: Path) -> None:
    """The whole point. Determinism is not independent reproduction."""
    same = attest(bundle)
    assert machine_relation(bundle, same) == SAME_MACHINE

    promotion = promotion_for(bundle, [same])
    assert promotion["state"] == TrustState.LOCAL.value
    assert "demonstrates determinism" in promotion["reason"]


def test_a_different_machine_reaches_community_validated(bundle: Path) -> None:
    elsewhere = attest(bundle, hardware=ELSEWHERE)
    assert machine_relation(bundle, elsewhere) == DIFFERENT_MACHINE
    assert promotion_for(bundle, [elsewhere])["state"] == TrustState.COMMUNITY_VALIDATED.value


def test_only_a_signed_independent_attestation_reaches_reproduced(bundle: Path) -> None:
    unsigned = attest(bundle, hardware=ELSEWHERE)
    signed = attest(bundle, hardware=ELSEWHERE, signature="cosign:deadbeef")

    assert promotion_for(bundle, [unsigned])["state"] == TrustState.COMMUNITY_VALIDATED.value
    assert promotion_for(bundle, [signed])["state"] == TrustState.REPRODUCED.value


def test_unsigned_is_recorded_as_a_claim_not_proof(bundle: Path) -> None:
    got = attest(bundle, hardware=ELSEWHERE)
    assert got["signed"] is False
    assert "not proof" in promotion_for(bundle, [got])["reason"]


def test_an_unstated_machine_is_neither_same_nor_different(bundle: Path) -> None:
    """Guessing in either direction would be a claim the data does not support."""
    blank = attest(bundle, hardware={})
    blank["hardware_profile"] = {"unset": True}
    # A profile that shares no fields with the bundle's still compares as
    # different; the unknown case is when one side has nothing at all.
    empty = {**attest(bundle), "hardware_profile": {}}
    assert machine_relation(bundle, empty) == UNKNOWN_MACHINE
    promotion = promotion_for(bundle, [empty])
    assert promotion["state"] == TrustState.LOCAL.value


def test_maintainer_verified_is_never_awarded_by_a_machine(bundle: Path) -> None:
    """It records a human judgement, and a machine cannot make one."""
    many = [attest(bundle, hardware=ELSEWHERE, signature=f"sig{i}") for i in range(20)]
    promotion = promotion_for(bundle, many)
    assert promotion["state"] != TrustState.MAINTAINER_VERIFIED.value
    assert "a machine cannot make one" in promotion["note"]


# --- an attestation is bound to one bundle ----------------------------------


def test_an_attestation_cannot_be_moved_to_another_bundle(bundle: Path, tmp_path: Path) -> None:
    """Otherwise it is a sticker, not evidence."""
    other = tmp_path / "other.tooltrace"
    shutil.copytree(bundle, other)
    got = attest(bundle)
    problems = verify_attestation(other, got)
    assert problems
    assert any("not" in p for p in problems)


def test_editing_the_bundle_invalidates_its_attestations(bundle: Path) -> None:
    got = attest(bundle)
    assert verify_attestation(bundle, got) == []

    manifest = bundle / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["trust_state"] = "MAINTAINER_VERIFIED"
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")

    problems = verify_attestation(bundle, got)
    assert any("different version of this bundle" in p for p in problems)


def test_the_digest_survives_reformatting(bundle: Path) -> None:
    """Over canonical JSON, so pretty-printing does not invalidate everything."""
    before = manifest_digest(bundle)
    manifest = bundle / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest.write_text(json.dumps(data, indent=8, sort_keys=False), encoding="utf-8")
    assert manifest_digest(bundle) == before


def test_a_malformed_attestation_is_rejected_with_reasons(bundle: Path) -> None:
    problems = verify_attestation(bundle, {"schema": SCHEMA})
    assert len(problems) >= 3
    assert all("missing required field" in p for p in problems)


def test_an_unknown_outcome_is_rejected(bundle: Path) -> None:
    got = attest(bundle)
    got["outcome"] = "sort of"
    assert any("unknown outcome" in p for p in verify_attestation(bundle, got))


def test_a_rejected_attestation_is_reported_not_silently_dropped(bundle: Path) -> None:
    bad = attest(bundle)
    bad["bundle"] = "somewhere-else.tooltrace"
    promotion = promotion_for(bundle, [bad])
    assert promotion["rejected"]
    assert promotion["sound_attestations"] == 0


def test_a_failed_reproduction_does_not_promote(bundle: Path) -> None:
    got = attest(bundle, hardware=ELSEWHERE, reproduced=False)
    promotion = promotion_for(bundle, [got])
    assert promotion["state"] == TrustState.LOCAL.value
    assert "none reports a successful reproduction" in promotion["reason"]


# --- rendering --------------------------------------------------------------


def test_an_unattested_bundle_says_so_plainly(bundle: Path) -> None:
    rendered = render_markdown(bundle.name, [], promotion_for(bundle, []))
    assert "reproduced by nobody but its author" in rendered


def test_the_rendering_always_states_what_unsigned_means(bundle: Path) -> None:
    got = attest(bundle, hardware=ELSEWHERE)
    got["_machine"] = DIFFERENT_MACHINE
    rendered = render_markdown(bundle.name, [got], promotion_for(bundle, [got]))
    assert "is not the same as proof" in rendered


# --- the CLI ----------------------------------------------------------------


def test_the_cli_reads_an_unattested_bundle(bundle: Path, capsys) -> None:
    assert main(["attest", str(bundle), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["attestations"] == []
    assert payload["promotion"]["state"] == TrustState.LOCAL.value


def test_the_cli_records_an_attestation_by_reproducing(bundle: Path, capsys) -> None:
    code = main(["attest", str(bundle), "--attester", "alice", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["attestations"][0]["attester"] == "alice"
    assert payload["attestations"][0]["outcome"] == "reproduced"
    # Same machine as the one that wrote the bundle, so no promotion.
    assert payload["promotion"]["state"] == TrustState.LOCAL.value


def test_attestations_are_appended_never_rewritten(bundle: Path, capsys) -> None:
    """A store that can be edited in place is a store nobody can check."""
    main(["attest", str(bundle), "--attester", "alice", "--json"])
    capsys.readouterr()
    main(["attest", str(bundle), "--attester", "bob", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert [a["attester"] for a in payload["attestations"]] == ["alice", "bob"]

    lines = (bundle / "attestations.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_promoting_says_that_it_stales_existing_attestations(bundle: Path, capsys) -> None:
    """Promotion rewrites the manifest, which every attestation is bound to."""
    main(["attest", str(bundle), "--attester", "alice", "--promote", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["promoted"] is True
    assert "Re-attest after promoting" in payload["promotion"]["note"]


def test_the_cli_refuses_a_path_that_is_not_a_bundle(tmp_path: Path, capsys) -> None:
    assert main(["attest", str(tmp_path / "nope")]) != 0
    assert "not a bundle directory" in capsys.readouterr().err


def test_every_committed_bundle_is_honestly_local() -> None:
    """No bundle here claims a trust state nothing produced.

    The ladder's four levels were unreachable; if a committed bundle were
    labelled above LOCAL it would be a claim with no evidence behind it.
    """
    from tooltrace.artifacts.bundles import load_bundle_result

    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    for path in bundles:
        assert load_bundle_result(path).trust_state == TrustState.LOCAL
