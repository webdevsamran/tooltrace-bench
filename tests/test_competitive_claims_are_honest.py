"""Competitive facts must be generated, dated, and stated once.

`docs/competitive-analysis.md` carried a CI-checked generated table *and*, twenty
lines below it, a hand-written "Landscape summary" dated three weeks earlier
that disagreed with it — SWE-bench pushed 2026-08-18 against the generated
2026-09-02, SWE-bench-Live at ~224 stars against 234. Three of the hand table's
eighteen projects were never fetched at all, and two of those had moved to a new
org, so no refresh could ever have corrected them.

A document that contradicts itself in two adjacent tables is worse than one with
no table: a reader cannot tell which half to believe, and the generated half is
the one that looks least authoritative because it has no prose around it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "competitive-analysis.md"
_META = _ROOT / "data" / "competitor-meta.json"
_REGISTRY = _ROOT / "data" / "competitor-registry.json"

_OPEN = "<!-- landscape:generated -->"
_CLOSE = "<!-- /landscape:generated -->"


def _text() -> str:
    return _DOC.read_text(encoding="utf-8")


def _meta() -> dict:
    return json.loads(_META.read_text(encoding="utf-8"))


def _registry() -> dict:
    return json.loads(_REGISTRY.read_text(encoding="utf-8"))


def _outside_generated_block(text: str) -> str:
    head, rest = text.split(_OPEN, 1)
    _, tail = rest.split(_CLOSE, 1)
    return head + tail


def test_the_registry_and_the_fetched_data_cover_the_same_projects() -> None:
    """One list of tracked projects, not two that can disagree."""
    requested = {p["slug"] for p in _registry()["projects"]}
    fetched = {entry.get("requested") or entry["repo"] for entry in _meta()["repos"].values()}
    assert requested == fetched, (
        "data/competitor-registry.json and data/competitor-meta.json disagree about "
        f"which projects are tracked; run scripts/fetch_competitor_meta.py. "
        f"Only in registry: {sorted(requested - fetched)}. Only in data: {sorted(fetched - requested)}"
    )


def test_every_project_carries_a_category() -> None:
    """Category is the one human judgement; it must be present and labelled."""
    missing = [e["repo"] for e in _meta()["repos"].values() if not e.get("category")]
    assert not missing, f"projects with no category: {missing}"


def test_no_star_bearing_table_exists_outside_the_generated_block() -> None:
    """This is the specific defect: a second, hand-maintained table of the same facts."""
    outside = _outside_generated_block(_text())
    offenders = []
    for line in outside.splitlines():
        if not line.strip().startswith("|"):
            continue
        if re.search(r"\bStars\b", line) or re.search(r"~\s*\d+(\.\d+)?k\b", line):
            offenders.append(line.strip()[:90])
    assert not offenders, (
        "a table outside the generated block carries star counts; repository facts "
        "belong to the fetch, not to prose: " + " | ".join(offenders)
    )


def test_the_document_has_no_second_refresh_date() -> None:
    """The generated block states its own fetch date; a second one goes stale."""
    outside = _outside_generated_block(_text())
    stale = [
        line.strip()
        for line in outside.splitlines()
        if re.match(r"^\s*Last refreshed:", line) and not line.strip().startswith(">")
    ]
    assert not stale, f"a hand-maintained refresh date is back: {stale}"


def test_the_generated_block_reports_the_fetch_date_from_the_data() -> None:
    text = _text()
    block = text.split(_OPEN, 1)[1].split(_CLOSE, 1)[0]
    match = re.search(r"fetched (\d{4}-\d{2}-\d{2})", block)
    assert match, "the generated block no longer states its fetch date"
    assert match.group(1) == _meta()["fetched_utc"][:10]


def test_moved_projects_are_recorded_rather_than_silently_followed() -> None:
    """GitHub follows renames; a reader who knows the old name should see the move."""
    moved = {
        (e["requested"], e["repo"])
        for e in _meta()["repos"].values()
        if e.get("requested") and e["requested"] != e["repo"]
    }
    if not moved:
        pytest.skip("no tracked project has been renamed")
    block = _text().split(_OPEN, 1)[1].split(_CLOSE, 1)[0]
    for old, new in moved:
        assert new in block, f"{new} is missing from the table"
        assert f"moved from {old}" in block, f"the table does not record that {old} moved to {new}"


def test_bfcl_is_cited_by_its_leaderboard_not_a_release_tag() -> None:
    """BFCL's generations version the leaderboard, not the repository.

    The repo's release tags stop at v1.3; citing a GitHub release for "BFCL v4"
    would cite something that does not exist.
    """
    text = _text()
    assert "ShishirPatil/gorilla" in text, "BFCL is not covered at all"
    section = text[text.index("### BFCL") :]
    section = section[: section.index("\n### ")] if "\n### " in section else section
    assert "gorilla.cs.berkeley.edu" in section, "BFCL must be cited by its leaderboard"
    releases = _meta()["repos"]["ShishirPatil/gorilla"].get("latest_release") or {}
    assert releases.get("tag") == "v1.3", (
        "the Gorilla repo's latest release tag changed; re-check the citation note, "
        f"which says tags stop at v1.3 (now {releases.get('tag')!r})"
    )


def test_the_security_section_does_not_claim_a_capability_we_lack() -> None:
    """Listing security benchmarks must not imply we measure what they measure."""
    text = _text()
    assert "agentdojo" in text
    section = text[text.index("### agentdojo") :]
    section = section[: section.index("\n### ")] if "\n### " in section else section
    assert "does not currently measure" in section, (
        "the security section must state plainly that this project does not "
        "measure prompt-injection resilience today"
    )


def test_the_readme_project_count_and_date_match_the_data() -> None:
    """A count typed into prose is a number that can drift from its source."""
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    data = _meta()
    match = re.search(r"(\d+) projects are tracked in", readme)
    assert match, "README no longer states how many projects are tracked"
    assert int(match.group(1)) == len(data["repos"]), (
        f"README claims {match.group(1)} tracked projects; "
        f"data/competitor-meta.json has {len(data['repos'])}"
    )
    date = re.search(r"fetched from the GitHub API on (\d{4}-\d{2}-\d{2})", readme)
    assert date, "README no longer states the fetch date"
    assert date.group(1) == data["fetched_utc"][:10], (
        f"README says the data was fetched {date.group(1)}; "
        f"the data says {data['fetched_utc'][:10]}"
    )
