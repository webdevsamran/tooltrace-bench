"""NIST AI RMF and ISO/IEC 42001, and the controls no benchmark can reach.

`evidence.py` files what a run set measured against the EU AI Act. These are the
same facts in two other vocabularies -- and the mapping is mostly refusals,
because both frameworks are far larger than anything a harness can speak to.

The property under test throughout is that a **partial mapping is never
presentable as coverage**. A tool that listed only the controls it could
evidence would read, to a reviewer skimming a table, as a project that covers
NIST AI RMF. It does not, it cannot, and no future version will: GOVERN is about
policy and MAP is about deployment context, and those are not things a run
observes.

The regulatory changelog is tested against the real `CHANGELOG.md` for the same
reason. A regulatory document that has quietly drifted from the release history
is worse than none, because it is the one a reviewer would trust.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from tooltrace.analysis.frameworks import (
    EVIDENCED,
    FRAMEWORKS,
    NOT_RUN,
    OUT_OF_SCOPE,
    RELEASE_EVIDENCE,
    map_controls,
    regulatory_changelog,
    render_markdown,
)

ROOT = Path(__file__).resolve().parents[1]


def facts(n: int = 3, *, security: bool = True, verified: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "bundle": f"b{i}",
            "verified": verified,
            "task_id": "file-editing/fix-config-typo",
            "agent": "scripted",
            "success": True,
            "trust_state": "LOCAL",
        }
        for i in range(n)
    ]
    if security:
        rows.append(
            {
                "bundle": "b-sec",
                "verified": verified,
                "task_id": "security/instruction-hierarchy",
                "agent": "scripted",
                "success": True,
                "trust_state": "LOCAL",
            }
        )
    return rows


# --- the refusal ------------------------------------------------------------


@pytest.mark.parametrize("framework", sorted(FRAMEWORKS))
def test_every_framework_lists_controls_no_benchmark_can_evidence(framework: str) -> None:
    """The rows that stop a partial mapping reading as coverage."""
    mapping = map_controls(framework, facts())
    out_of_scope = [c for c in mapping["controls"] if c["state"] == OUT_OF_SCOPE]
    assert out_of_scope, f"{framework} claims a harness can evidence everything it lists"


@pytest.mark.parametrize("framework", sorted(FRAMEWORKS))
def test_an_out_of_scope_control_never_acquires_evidence(framework: str) -> None:
    """No quantity of runs makes a policy evidenceable."""
    mapping = map_controls(framework, facts(500))
    for control in mapping["controls"]:
        if control["state"] == OUT_OF_SCOPE:
            assert control["evidence"] == []


@pytest.mark.parametrize("framework", sorted(FRAMEWORKS))
def test_every_out_of_scope_control_says_why(framework: str) -> None:
    """On those rows the reason is the entire content."""
    mapping = map_controls(framework, facts())
    for control in mapping["controls"]:
        if control["state"] == OUT_OF_SCOPE:
            assert len(control["note"]) > 20, control["id"]


@pytest.mark.parametrize("framework", sorted(FRAMEWORKS))
def test_the_statement_says_the_table_is_a_subset(framework: str) -> None:
    """A reviewer must not read eleven rows as the whole of the AI RMF."""
    assert (
        "the framework is larger than this table" in map_controls(framework, facts())["statement"]
    )


def test_nist_is_described_as_voluntary_with_no_pass_mark() -> None:
    mapping = map_controls("nist-ai-rmf", facts())
    assert "voluntary" in mapping["kind"]
    assert "no pass mark" in mapping["caveat"]


def test_iso_says_it_certifies_a_management_system_not_a_run() -> None:
    """The most likely misreading, so it is stated first."""
    mapping = map_controls("iso-42001", facts())
    assert "management system" in mapping["caveat"]
    assert "cannot be presented as progress toward one" in mapping["caveat"]


def test_governance_and_context_categories_are_out_of_scope() -> None:
    mapping = map_controls("nist-ai-rmf", facts())
    states = {c["id"]: c["state"] for c in mapping["controls"]}
    for control in ("GOVERN-1", "GOVERN-4", "MAP-1", "MAP-5"):
        assert states[control] == OUT_OF_SCOPE


def test_the_management_system_clauses_are_out_of_scope() -> None:
    mapping = map_controls("iso-42001", facts())
    states = {c["id"]: c["state"] for c in mapping["controls"]}
    assert states["Clause 5"] == OUT_OF_SCOPE
    assert states["Clause 7.2"] == OUT_OF_SCOPE


# --- what runs actually evidence --------------------------------------------


def test_measurement_categories_pick_up_evidence_from_runs() -> None:
    mapping = map_controls("nist-ai-rmf", facts())
    states = {c["id"]: c["state"] for c in mapping["controls"]}
    assert states["MEASURE-1"] == EVIDENCED
    assert states["MEASURE-2"] == EVIDENCED


def test_the_security_category_needs_security_runs() -> None:
    """Without an adversarial run it is `not_run`, not evidenced and not absent.

    A row that vanished when nobody ran it would leave a reviewer unable to tell
    "we tested this" from "we never tried".
    """
    without = map_controls("nist-ai-rmf", facts(security=False))
    states = {c["id"]: c["state"] for c in without["controls"]}
    assert states["MEASURE-2.7"] == NOT_RUN

    with_security = map_controls("nist-ai-rmf", facts(security=True))
    assert {c["id"]: c["state"] for c in with_security["controls"]}["MEASURE-2.7"] == EVIDENCED


def test_the_logging_control_reports_how_many_bundles_verified() -> None:
    mapping = map_controls("iso-42001", facts(3, verified=False))
    row = next(c for c in mapping["controls"] if c["id"] == "A.6.2.8")
    assert "0 of 4" in row["evidence"][0]


def test_no_runs_leaves_every_in_scope_control_not_run() -> None:
    mapping = map_controls("nist-ai-rmf", [])
    assert not [c for c in mapping["controls"] if c["state"] == EVIDENCED]
    assert mapping["counts"]["evidenced"] == 0


def test_an_unknown_framework_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown framework"):
        map_controls("soc2", facts())


def test_every_framework_records_which_revision_it_maps() -> None:
    """A mapping to an undated framework is a mapping nobody can check."""
    for framework in FRAMEWORKS.values():
        assert framework.revision


# --- rendering --------------------------------------------------------------


def test_the_rendered_table_keeps_the_out_of_scope_rows() -> None:
    """Dropping them from the readable output would undo the whole design."""
    rendered = render_markdown(map_controls("nist-ai-rmf", facts()))
    assert "GOVERN-1" in rendered
    assert OUT_OF_SCOPE in rendered


def test_the_rendered_table_leads_with_the_caveat() -> None:
    rendered = render_markdown(map_controls("iso-42001", facts()))
    header, _, rest = rendered.partition("| Control |")
    assert "management system" in header, "the caveat must precede the table, not follow it"
    assert rest


# --- the regulatory changelog -----------------------------------------------


def changelog_versions() -> set[str]:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return set(re.findall(r"^## \[([^\]]+)\]", text, re.MULTILINE))


def test_every_release_named_here_exists_in_the_changelog() -> None:
    """A regulatory document that has drifted from the release history is worse
    than none, because it is the one a reviewer would trust."""
    named = {entry.version for entry in RELEASE_EVIDENCE}
    missing = named - changelog_versions()
    assert not missing, f"these versions are not in CHANGELOG.md: {sorted(missing)}"


def test_every_released_version_is_accounted_for_here() -> None:
    """Including the ones that changed nothing about evidence.

    Omitting those would make the list read as steady regulatory progress
    rather than as a record.
    """
    missing = changelog_versions() - {entry.version for entry in RELEASE_EVIDENCE}
    assert not missing, f"these releases have no regulatory entry: {sorted(missing)}"


def test_a_release_that_added_no_capability_is_listed_anyway() -> None:
    empty = [e for e in RELEASE_EVIDENCE if not e.first_evidenced]
    assert empty, "every release adding a capability would be a suspicious record"
    assert any("No new evidence capability" in e.summary for e in empty)


def test_no_identifier_is_claimed_by_two_releases() -> None:
    """ "First evidenced" means first. A duplicate would make the date meaningless."""
    seen: set[str] = set()
    for entry in RELEASE_EVIDENCE:
        for identifier in entry.first_evidenced:
            assert identifier not in seen, f"{identifier} is claimed twice"
            seen.add(identifier)


def test_every_identifier_is_a_real_control_or_article() -> None:
    """An entry citing a control nothing maps is a claim about nothing."""
    known = {c.id for framework in FRAMEWORKS.values() for c in framework.controls}
    from tooltrace.analysis.evidence import OBLIGATIONS

    known |= {article for article, _title in OBLIGATIONS}
    for entry in RELEASE_EVIDENCE:
        for identifier in entry.first_evidenced:
            assert identifier in known, f"{identifier} is not a control this project maps"


def test_the_changelog_says_capability_is_not_compliance() -> None:
    assert "not satisfying it" in regulatory_changelog()["caveat"]


def test_the_eu_articles_are_all_reachable_by_now() -> None:
    """Every article the dossier organises evidence against has a release date."""
    from tooltrace.analysis.evidence import OBLIGATIONS

    reached = set(regulatory_changelog()["evidenceable_now"])
    for article, _title in OBLIGATIONS:
        assert article in reached, f"{article} is in the dossier and in no release entry"


# --- the bundle-path bug this lane uncovered --------------------------------


def test_naming_a_single_bundle_works(tmp_path: Path) -> None:
    """`--bundles one.tooltrace` reported "no bundles found" for one right there.

    A `.tooltrace` bundle *is* a directory, so "is it a directory" cannot tell a
    bundle from a folder of bundles -- and that was the test. Naming a single
    bundle globbed inside it and found nothing.
    """
    from tooltrace.cli.main import _expand_bundles

    single = tmp_path / "one.tooltrace"
    single.mkdir()
    (single / "manifest.json").write_text("{}", encoding="utf-8")
    assert _expand_bundles([str(single)]) == [single]


def test_naming_a_containing_directory_still_works(tmp_path: Path) -> None:
    container = tmp_path / "results"
    container.mkdir()
    for name in ("a", "b"):
        made = container / f"{name}.tooltrace"
        made.mkdir()
        (made / "manifest.json").write_text("{}", encoding="utf-8")
    assert len(_expanded(container)) == 2


def _expanded(container: Path) -> list[Path]:
    from tooltrace.cli.main import _expand_bundles

    return _expand_bundles([str(container)])


def test_a_bundle_with_no_manifest_is_picked_up_and_not_skipped(tmp_path: Path) -> None:
    """It is corrupt, and vanishing from the count is the worse failure."""
    from tooltrace.cli.main import _expand_bundles

    broken = tmp_path / "broken.tooltrace"
    broken.mkdir()
    assert _expand_bundles([str(broken)]) == [broken]


def test_a_file_path_is_ignored_rather_than_raising(tmp_path: Path) -> None:
    from tooltrace.cli.main import _expand_bundles

    note = tmp_path / "notes.txt"
    note.write_text("not a bundle", encoding="utf-8")
    assert _expand_bundles([str(note)]) == []
