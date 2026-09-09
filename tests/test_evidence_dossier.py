"""An evidence dossier must never become a compliance claim.

The remaining EU AI Act provisions became applicable on 2 August 2026, and the
phrase every compliance guide repeats is that an organisation must
*demonstrate* compliance rather than claim it. A checksummed, reproducible
`.tooltrace` bundle is already evidence for exactly that.

The risk in building this is the obvious one. A tool that emitted a "compliant"
verdict from a benchmark run would be actively misleading in a domain carrying
€35M penalties, and the fact that a machine produced it would lend it unearned
authority. So most of this file tests what the dossier *refuses* to say: every
obligation must carry a stated gap, the output must declare it is not a
determination, and no rendering may contain a bare claim of compliance.

The hash chain is tested the only way that means anything — by altering a run
and asserting the chain notices.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tooltrace.analysis.evidence import (
    OBLIGATIONS,
    build_dossier,
    build_obligations,
    render_markdown,
    verify_chain,
)
from tooltrace.cli.main import main

_ROOT = Path(__file__).resolve().parent.parent
_RESULTS = _ROOT / "results"
_WHEN = "2026-09-09T00:00:00+00:00"


def _bundles() -> list[Path]:
    bundles = sorted(_RESULTS.glob("*.tooltrace"))
    if not bundles:
        pytest.skip("no committed bundles")
    return bundles


@pytest.fixture(scope="module")
def dossier() -> dict:
    return build_dossier(_bundles(), generated_at=_WHEN)


# --- what it refuses to say -------------------------------------------------


def test_every_obligation_states_a_gap(dossier: dict) -> None:
    """An obligation with no stated gap reads as fully satisfied."""
    for obligation in dossier["obligations"]:
        assert obligation["gaps"], f"{obligation['article']} claims no gaps at all"


def test_the_dossier_declares_it_is_not_a_determination(dossier: dict) -> None:
    assert "not a compliance determination" in dossier["statement"]
    assert "organisational determination" in dossier["statement"]


def test_the_rendering_leads_with_that_disclaimer(dossier: dict) -> None:
    markdown = render_markdown(dossier)
    head = markdown[: markdown.index("## Runs")]
    assert "not a compliance determination" in head


def test_no_rendering_asserts_compliance(dossier: dict) -> None:
    """The specific failure mode: a machine-produced 'compliant' verdict."""
    text = render_markdown(dossier) + json.dumps(dossier)
    forbidden = re.compile(
        r"\b(is compliant|are compliant|fully compliant|compliance achieved|certified)\b", re.I
    )
    match = forbidden.search(text)
    assert match is None, f"the dossier asserts compliance: {match.group(0) if match else ''}"


def test_the_cli_says_so_in_its_payload(capsys) -> None:
    assert main(["evidence", "--bundles", str(_RESULTS), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["is_compliance_determination"] is False


def test_a_small_sample_is_called_out(dossier: dict) -> None:
    """Six runs is not a stable accuracy measurement and must not read as one."""
    accuracy = next(o for o in dossier["obligations"] if o["article"] == "Article 15")
    assert any("Sample size" in gap for gap in accuracy["gaps"])


def test_absent_security_evidence_is_named_not_omitted(dossier: dict) -> None:
    accuracy = next(o for o in dossier["obligations"] if o["article"] == "Article 15")
    if not any(str(r["task_id"]).startswith("security/") for r in dossier["runs"]):
        assert any("Cybersecurity evidence is absent" in gap for gap in accuracy["gaps"])


def test_checksums_are_described_as_tamper_evident_not_tamper_proof(dossier: dict) -> None:
    logging = next(o for o in dossier["obligations"] if o["article"] == "Article 12")
    assert any("tamper-evident, not tamper-proof" in gap for gap in logging["gaps"])


# --- what it does record ----------------------------------------------------


def test_every_obligation_in_the_set_appears(dossier: dict) -> None:
    articles = {o["article"] for o in dossier["obligations"]}
    assert articles == {article for article, _ in OBLIGATIONS}


def test_each_run_records_what_a_reviewer_needs(dossier: dict) -> None:
    for run in dossier["runs"]:
        for field in ("bundle", "task_id", "task_version", "agent", "verified", "created_at"):
            assert field in run, f"{field} missing from a run record"


def test_the_dossier_is_reproducible() -> None:
    """The timestamp is injected, so two builds of the same bundles agree."""
    first = build_dossier(_bundles(), generated_at=_WHEN)
    second = build_dossier(_bundles(), generated_at=_WHEN)
    assert first["chain_head"] == second["chain_head"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- the hash chain ---------------------------------------------------------


def test_an_intact_chain_verifies(dossier: dict) -> None:
    assert verify_chain(dossier) == []


def test_altering_a_run_breaks_the_chain(dossier: dict) -> None:
    """A chain that cannot detect alteration is decoration."""
    tampered = json.loads(json.dumps(dossier))
    tampered["runs"][0]["success"] = not tampered["runs"][0]["success"]
    problems = verify_chain(tampered)
    assert problems and "altered" in problems[0]


def test_removing_a_run_breaks_the_chain(dossier: dict) -> None:
    """Each entry commits to the previous one, so a deletion is detectable."""
    tampered = json.loads(json.dumps(dossier))
    tampered["runs"].pop(0)
    assert verify_chain(tampered)


def test_a_replaced_chain_head_is_detected(dossier: dict) -> None:
    tampered = json.loads(json.dumps(dossier))
    tampered["chain_head"] = "0" * 64
    assert verify_chain(tampered)


# --- unverified bundles are surfaced ---------------------------------------


def test_an_unverified_bundle_is_recorded_and_warned(tmp_path: Path, capsys) -> None:
    import shutil

    broken = tmp_path / "b.tooltrace"
    shutil.copytree(_bundles()[0], broken)
    (broken / "result.json").write_text("{}", encoding="utf-8")

    code = main(["evidence", "--bundles", str(tmp_path), "--json"])
    captured = capsys.readouterr()
    assert code == 0, "an unverified bundle is reported, not a crash"
    payload = json.loads(captured.out)
    assert payload["unverified"] == ["b.tooltrace"]
    assert "failed checksum verification" in captured.err


def test_writing_the_dossier_produces_both_formats(tmp_path: Path) -> None:
    out = tmp_path / "evidence"
    assert main(["evidence", "--bundles", str(_RESULTS), "--out", str(out), "--json"]) == 0
    assert (out / "evidence.json").is_file()
    assert (out / "evidence.md").is_file()
    written = json.loads((out / "evidence.json").read_text(encoding="utf-8"))
    assert verify_chain(written) == []


def test_no_bundles_is_a_usage_error(tmp_path: Path) -> None:
    assert main(["evidence", "--bundles", str(tmp_path)]) != 0


def test_obligations_can_be_built_from_no_runs() -> None:
    """An empty dossier must still state its gaps rather than crash."""
    obligations = build_obligations([])
    assert len(obligations) == len(OBLIGATIONS)
    for obligation in obligations:
        assert obligation.gaps
