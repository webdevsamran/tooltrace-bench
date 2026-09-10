"""Redaction: what was removed, what shapes remain, and the two refusals.

Sharing a trace means sharing whatever the agent read and wrote, and "we ran a
redactor" is not a statement anyone can act on. This produces the statement --
and the most important thing it produces is what it will not say.

**A clean scan is not proof of absence.** Every detector matches a shape. A
person's name has none, and neither does a sentence about them. A report saying
"no PII found" would be read as "safe to publish" and would be wrong in exactly
the cases that matter.

**It is not differential privacy.** DP means calibrated noise under an epsilon
budget; a bundle exists to be reproduced byte for byte. Adding noise would break
the property the artifact is for, so the word is refused rather than borrowed.

Both refusals are asserted below, because they are the feature.
"""

from __future__ import annotations

import json
from pathlib import Path

from tooltrace.security.redaction import (
    PII_PATTERNS,
    UNDETECTABLE,
    certificate,
    redaction_report,
    render_markdown,
    write_record,
)


def bundle(tmp_path: Path, name: str, trace_text: str, diff: str = "") -> Path:
    path = tmp_path / f"{name}.tooltrace"
    path.mkdir(parents=True)
    (path / "trace.jsonl").write_text(trace_text, encoding="utf-8")
    if diff:
        (path / "workspace.diff").write_text(diff, encoding="utf-8")
    return path


# --- it finds what it claims to find ----------------------------------------


def test_an_email_address_in_a_trace_is_reported(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", '{"payload": {"text": "write to ana@example.com"}}')
    report = redaction_report(path)
    labels = {f["label"] for f in report["pii_findings"]}
    assert "email-address" in labels


def test_a_finding_says_which_file_it_was_in(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", "{}", diff="+contact: ana@example.com")
    finding = next(
        f for f in redaction_report(path)["pii_findings"] if f["label"] == "email-address"
    )
    assert finding["files"] == ["workspace.diff"]


def test_a_finding_never_quotes_the_value_it_found(tmp_path: Path) -> None:
    """A report that printed the personal data it found would be the disclosure."""
    path = bundle(tmp_path, "b", '{"text": "ana@example.com and 123-45-6789"}')
    serialised = json.dumps(redaction_report(path))
    assert "ana@example.com" not in serialised
    assert "123-45-6789" not in serialised


def test_several_shapes_are_counted_separately(tmp_path: Path) -> None:
    path = bundle(
        tmp_path,
        "b",
        '{"text": "ana@example.com, 123-45-6789, DE44500105175407324931"}',
    )
    labels = {f["label"] for f in redaction_report(path)["pii_findings"]}
    assert {"email-address", "us-ssn-like", "iban"} <= labels


def test_a_clean_bundle_reports_no_findings(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", '{"payload": {"tool": "read_file", "path": "a.txt"}}')
    assert redaction_report(path)["pii_findings"] == []


# --- the first refusal: a clean scan is not proof of absence -----------------


def test_a_clean_scan_says_it_is_not_proof_of_absence(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", '{"payload": {"tool": "read_file"}}')
    assert "not the same as none present" in redaction_report(path)["statement"]


def test_every_report_names_what_it_cannot_detect(tmp_path: Path) -> None:
    """A reader who sees seven patterns checked assumes seven is the problem."""
    path = bundle(tmp_path, "b", "{}")
    assert redaction_report(path)["undetectable"] == list(UNDETECTABLE)
    assert any("names" in item for item in UNDETECTABLE)


def test_the_report_refuses_to_answer_whether_it_is_safe_to_publish(tmp_path: Path) -> None:
    """`None`, not `True`. The decision is a human one and the field says so."""
    path = bundle(tmp_path, "b", "{}")
    report = redaction_report(path)
    assert report["safe_to_publish"] is None
    assert "human decision" in report["limit"]


def test_the_rendered_record_ends_with_what_it_cannot_see(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", "{}")
    rendered = render_markdown(certificate([path], generated_at="2026-09-10T00:00:00Z"))
    assert "What this scan cannot see" in rendered
    assert "not permission to publish" in rendered


# --- the second refusal: this is not differential privacy -------------------


def test_the_report_says_it_is_not_differential_privacy(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", "{}")
    note = redaction_report(path)["not_differential_privacy"]
    assert "epsilon" in note
    assert "byte for byte" in note


def test_the_word_certification_is_refused_in_the_output(tmp_path: Path) -> None:
    """The function is named for what people search for; the content refuses it."""
    record = certificate([bundle(tmp_path, "b", "{}")], generated_at="2026-09-10T00:00:00Z")
    assert record["is_certification"] is False
    assert "not a certification" in record["statement"]
    assert "not a certification" in render_markdown(record).lower()


# --- a residual secret is a defect in the sanitiser -------------------------


def test_a_secret_surviving_sanitisation_is_called_a_defect(tmp_path: Path) -> None:
    """Not a finding about the run: the sanitiser claims to catch this class."""
    path = bundle(tmp_path, "b", '{"text": "sk-abcdefghijklmnopqrstuvwx"}')
    report = redaction_report(path)
    assert "openai-style-key" in report["residual_secret_classes"]
    assert "defect in the sanitiser" in report["statement"]


def test_a_redaction_marker_is_counted_as_evidence_the_sanitiser_ran(tmp_path: Path) -> None:
    """Taken from the artifact rather than assumed."""
    path = bundle(tmp_path, "b", '{"text": "[REDACTED] and [REDACTED]"}')
    assert redaction_report(path)["redaction_markers"] == 2


def test_no_markers_is_reported_as_nothing_matched_not_as_nothing_ran(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", '{"text": "ordinary"}')
    assert "nothing matched a secret pattern" in redaction_report(path)["statement"]


# --- across bundles ---------------------------------------------------------


def test_the_record_counts_bundles_with_findings(tmp_path: Path) -> None:
    clean = bundle(tmp_path, "clean", '{"text": "nothing here"}')
    dirty = bundle(tmp_path, "dirty", '{"text": "ana@example.com"}')
    record = certificate([clean, dirty], generated_at="2026-09-10T00:00:00Z")
    assert record["counts"]["scanned"] == 2
    assert record["counts"]["with_pii_shapes"] == 1


def test_an_unreadable_bundle_is_counted_rather_than_skipped(tmp_path: Path) -> None:
    """A bundle that silently vanished from the count would inflate the clean rate."""
    empty = tmp_path / "empty.tooltrace"
    empty.mkdir()
    record = certificate([empty], generated_at="2026-09-10T00:00:00Z")
    assert record["counts"]["unreadable"] == 1
    assert "unreadable" in render_markdown(record)


def test_the_record_is_written_in_both_formats(tmp_path: Path) -> None:
    path = bundle(tmp_path, "b", "{}")
    out = tmp_path / "out"
    written = write_record(certificate([path], generated_at="2026-09-10T00:00:00Z"), out)
    assert {p.name for p in written} == {"redaction.json", "redaction.md"}


# --- honesty about the detectors themselves ---------------------------------


def test_every_pattern_declares_its_own_weakness() -> None:
    """A high-false-positive detector presented without that note is a trap."""
    for label, _pattern, note in PII_PATTERNS:
        assert note, label
    notes = " ".join(note for _l, _p, note in PII_PATTERNS)
    assert "false-positive" in notes or "Shape only" in notes


def test_the_shipped_bundles_carry_no_residual_secret() -> None:
    """This project publishes its own bundles; a leak here would be a real one."""
    results = Path(__file__).resolve().parents[1] / "results"
    bundles = sorted(results.glob("*.tooltrace"))
    if not bundles:  # pragma: no cover - published bundles ship with the repo
        return
    record = certificate(bundles, generated_at="2026-09-10T00:00:00Z")
    assert record["counts"]["with_residual_secrets"] == 0


# --- the CLI ----------------------------------------------------------------


def test_the_cli_exits_non_zero_only_on_a_residual_secret(tmp_path: Path, capsys) -> None:
    from tooltrace.cli.main import main

    with_pii = bundle(tmp_path / "a", "b", '{"text": "ana@example.com"}')
    assert main(["redaction", "--bundles", str(with_pii)]) == 0, (
        "personal data is reported, never fatal: whether it matters depends on "
        "whose it is and where the bundle is going"
    )
    capsys.readouterr()

    with_secret = bundle(tmp_path / "c", "d", '{"text": "sk-abcdefghijklmnopqrstuvwx"}')
    assert main(["redaction", "--bundles", str(with_secret)]) == 9
    assert "still match a secret pattern" in capsys.readouterr().err
