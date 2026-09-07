"""`docs/feature-status.md` must not claim capabilities the repo does not have.

That document calls itself "the durable verification artifact for this pass"
and grades 122 capability targets. Eight of them were marked **I**
("implemented (code + tests)") citing evidence like "local web fixtures",
"knowledge fixtures", "devops fixtures" and "safe config-review fixtures".
None of those files exist. The only thing behind those rows was a member of
the `Domain` enum in `tooltrace/tasks/v2.py` -- the domain was *declarable*,
not runnable. Three further rows cited module paths (`analysis.py`,
`replay.py`, `perturbations.py`) that had become packages, so a reader
following the citation found nothing.

A verification document that is itself unverified is worse than no
verification document, because it converts "we did not check" into "we
checked". These tests make the checkable parts checkable.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "feature-status.md"
_TEXT = _DOC.read_text(encoding="utf-8")

_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.+?)\|\s*([A-Z])\s*\|(.+?)\|\s*$", re.M)

#: Where a bare path in the evidence column may be rooted. The table writes
#: `packs/git-workflow` for what is really `tooltrace/tasks/packs/git-workflow`.
_BASES = ("", "tooltrace/", "tooltrace/tasks/", "scripts/", "docs/")

#: A row about task packs, as opposed to one that merely says "pack" somewhere:
#: "Versioned task-pack indexes", "Cross-pack fingerprint dedup" and a policy
#: scope written "providers/models/tools/packs/network" are not pack rows. The
#: word has to stand on its own, which is what the trailing \b is for.
_PACK_SUBJECT = re.compile(r"(?:^|\s)[\w-]*packs\b", re.IGNORECASE)


def _rows() -> list[tuple[int, str, str, str]]:
    return [(int(n), cap.strip(), state, ev.strip()) for n, cap, state, ev in _ROW.findall(_TEXT)]


def _resolves(token: str) -> bool:
    """True if `token` names something on disk (or is plainly not a path)."""
    raw = token.strip()
    if raw.startswith("/"):
        return True  # a URL route such as /api/v1/events, not a file
    candidate = raw.lstrip("./")
    for base in _BASES:
        full = base + candidate
        if "*" in full:
            if list(_ROOT.glob(full)):
                return True
        elif (_ROOT / full).exists():
            return True
    if "/" not in candidate and candidate.endswith(".py"):
        return bool(list((_ROOT / "tooltrace").rglob(candidate)))
    return False


def test_the_table_still_parses() -> None:
    """A formatting slip must fail loudly, not silently check nothing."""
    rows = _rows()
    assert len(rows) == 122, f"expected 122 capability rows, parsed {len(rows)}"
    assert {n for n, _, _, _ in rows} == set(range(1, 123)), "row numbers are not 1..122"


def test_every_path_cited_as_evidence_exists() -> None:
    """The citation has to lead somewhere.

    Rows 70, 79 and 99 cited `analysis.py`, `tooltrace/replay.py` and
    `perturbations.py`. All three are packages now.
    """
    unresolved = [
        (num, token)
        for num, _, _, evidence in _rows()
        for token in re.findall(r"`([^`]+)`", evidence)
        if ("/" in token or token.endswith(".py")) and not _resolves(token)
    ]
    assert not unresolved, "feature-status.md cites paths that do not exist: " + ", ".join(
        f"row {n}: {p}" for n, p in unresolved
    )


def test_no_row_claims_a_task_pack_that_is_not_on_disk() -> None:
    """The specific defect: `I` rows for packs that were never written.

    A row whose capability text says "packs" and whose status is `I` has to
    point at a pack directory that exists. `S` rows are exempt by definition --
    that grade means the domain is declarable and nothing ships.
    """
    packs = {p.name for p in (_ROOT / "tooltrace" / "tasks" / "packs").iterdir() if p.is_dir()}
    offenders = []
    for num, capability, state, evidence in _rows():
        # "packs" as the subject of the row -- not "task-pack indexes",
        # "Cross-pack dedup", or a policy scope written "tools/packs/network".
        if state != "I" or not _PACK_SUBJECT.search(capability):
            continue
        cited = re.findall(r"`([^`]*packs?/([a-z0-9-]+))`", evidence)
        starred = "packs/*" in evidence
        if not starred and not any(name in packs for _, name in cited):
            offenders.append((num, capability))
    assert not offenders, "rows claim implemented task packs with no pack directory: " + "; ".join(
        f"#{n} {c}" for n, c in offenders
    )


def test_schema_only_rows_really_do_have_a_domain_and_nothing_more() -> None:
    """`S` is a real grade, not a place to hide work.

    Every `S` row names a domain the task schema admits; none of them may have
    a pack, because that is what would make them `I`.
    """
    domains = set(
        re.findall(
            r'^\s{4}([a-z_]+) = "\1"',
            (_ROOT / "tooltrace" / "tasks" / "v2.py").read_text(encoding="utf-8"),
            re.M,
        )
    )
    packs = {p.name for p in (_ROOT / "tooltrace" / "tasks" / "packs").iterdir() if p.is_dir()}
    schema_only = [(n, c, e) for n, c, _, e in _rows() if _grade(n) == "S"]
    assert len(schema_only) == 8, f"expected 8 schema-only rows, found {len(schema_only)}"
    for num, capability, evidence in schema_only:
        named = re.findall(r"`Domain\.([a-z_]+)`", evidence)
        assert named, f"row {num} is graded S but names no Domain value: {capability}"
        for value in named:
            assert value in domains, f"row {num} cites Domain.{value}, which v2.py does not define"
            assert value not in packs, (
                f"row {num} is graded S but tooltrace/tasks/packs/{value} exists -- "
                "if the pack ships, the row is I"
            )


def _grade(num: int) -> str:
    return next(state for n, _, state, _ in _rows() if n == num)


def test_the_summary_counts_match_the_table() -> None:
    """The old summary said 113 I / 7 E / 2 P and matched nothing.

    It double-counted #96 under both E and P, counted #20 as E when the table
    said E for a mock harness that does not exist, and one row carried an
    ad-hoc `I/P` grade that no legend defined.
    """
    counts = Counter(state for _, _, state, _ in _rows())
    summary = _TEXT[_TEXT.index("## Summary") :]
    for label, state in (
        (r"\*\*Implemented \(I\):\*\* (\d+)", "I"),
        (r"blocked \(E\):\*\* (\d+)", "E"),
        (r"\*\*Schema only \(S\):\*\* (\d+)", "S"),
        (r"completed this pass \(P\):\*\* (\d+)", "P"),
    ):
        match = re.search(label, summary)
        assert match, f"summary no longer states a count for {state}"
        assert int(match.group(1)) == counts[state], (
            f"summary claims {match.group(1)} {state} rows; the table has {counts[state]}"
        )
    assert sum(counts.values()) == 122


def test_the_legend_defines_every_grade_in_use() -> None:
    legend = _TEXT[: _TEXT.index("| # | Capability")]
    for state in sorted({state for _, _, state, _ in _rows()}):
        assert f"**{state}**" in legend, f"grade {state} is used in the table but not in the legend"


def test_the_roadmap_and_the_matrix_agree_about_browser_packs() -> None:
    """These two documents contradicted each other.

    feature-status.md marked browser packs implemented; ROADMAP.md listed
    browser fixtures as planned. Both cannot be true.
    """
    roadmap = (_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    planned = "browser fixtures" in roadmap
    if planned:
        assert _grade(11) != "I", (
            "ROADMAP lists browser fixtures as planned while feature-status.md "
            "marks row 11 implemented"
        )
