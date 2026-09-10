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

import importlib.util
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DOC = _ROOT / "docs" / "feature-status.md"
_TEXT = _DOC.read_text(encoding="utf-8")

_ROW = re.compile(r"^\|\s*(\d+)\s*\|(.+?)\|\s*([A-Z])\s*\|(.+?)\|\s*$", re.M)


def _refchecker() -> Any:
    """The single path resolver, shared with the CI script.

    This test used to keep its own copy, which is how the two drifted: the
    script grew a `removeprefix` fix that the test never got.
    """
    path = _ROOT / "scripts" / "check_doc_code_refs.py"
    spec = importlib.util.spec_from_file_location("check_doc_code_refs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_REFS = _refchecker()
_resolves = _REFS.resolves

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
        if _REFS.looks_like_path(token) and not _resolves(token)
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
        # The trailing `[^`]*` lets a row cite a *file inside* the pack rather
        # than only the directory. The earlier pattern required the backtick to
        # close immediately after the pack name, so it rejected more specific
        # evidence than it accepted -- which pushes authors towards vaguer
        # citations, the opposite of what this file is for.
        cited = re.findall(r"`([^`]*packs?/([a-z0-9-]+)[^`]*)`", evidence)
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
    # Three. It was eight, then seven when the security pack landed, and four
    # more left the grade when the database, browser, knowledge and devops packs
    # arrived -- browser and devops as **P** rather than **I**, because a saved
    # HTML file is not a live page and a CI config is not a container build.
    #
    # The number is asserted rather than merely computed so that a row cannot
    # drift *into* this grade unnoticed: `S` means a domain is declarable and
    # nothing runs, and that claim should only ever get rarer.
    assert len(schema_only) == 3, f"expected 3 schema-only rows, found {len(schema_only)}"
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
        (r"\*\*Declared only \(D\):\*\* (\d+)", "D"),
        (r"\*\*Not implemented \(N\):\*\* (\d+)", "N"),
    ):
        match = re.search(label, summary)
        if not match:
            assert counts[state] == 0, (
                f"the table has {counts[state]} {state} rows and the summary never mentions them"
            )
            continue
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


#: A capability claim mapped to a probe that answers "does anything ship?".
#: When the probe says nothing ships, no row *claiming to use* that capability
#: may be graded as working. This is the generic form of the judge defect: two
#: rows claimed multi-judge adapters and calibration datasets for three
#: releases, and no file matching `judge*.py` has ever existed.
#:
#: The claim patterns are phrases, not bare keywords, because a row may
#: legitimately mention a capability in order to say it is *not* used: row 44
#: claims "judge-independent deterministic scoring", which shipping no judge is
#: precisely the evidence for, not a contradiction of.
_CLAIM_PROBES: dict[str, tuple[re.Pattern[str], Callable[[], bool]]] = {
    "judge": (
        re.compile(r"multi-judge|judge adapter|judge calibration|judge drift", re.I),
        lambda: bool(list((_ROOT / "tooltrace").rglob("judge*.py"))),
    ),
    "calibration dataset": (
        re.compile(r"calibration dataset", re.I),
        lambda: bool(list((_ROOT / "tooltrace").rglob("calibrat*.py"))),
    ),
}

#: Grades that assert the capability works today.
_WORKING = {"I", "E", "P"}


def test_no_row_claims_a_capability_nothing_implements() -> None:
    offenders = []
    for name, (pattern, ships) in _CLAIM_PROBES.items():
        if ships():
            continue  # the capability exists; rows may claim it
        for num, capability, state, _ in _rows():
            if state in _WORKING and pattern.search(capability):
                offenders.append(f"#{num} claims {name!r} while no implementation of it ships")
    assert not offenders, "; ".join(offenders)


def test_every_working_row_cites_something_checkable() -> None:
    """Evidence has to be inspectable, not an assertion in prose.

    97 of the 122 rows cited bare prose such as "clustering module" or
    "calibration sets module", and the path check only inspected backticked
    tokens -- so three quarters of the table was never verified at all, which
    is how #42, #45, #46 and #121 survived as `I` with no implementation.

    `N` and `D` rows are exempt by definition: their whole content is that
    nothing ships, so there is nothing to cite.
    """
    bare = [
        (num, capability)
        for num, capability, state, evidence in _rows()
        if state in _WORKING and not re.findall(r"`[^`]+`", evidence)
    ]
    assert not bare, "rows assert a working capability with no checkable citation: " + "; ".join(
        f"#{n} {c}" for n, c in bare
    )


def test_the_claim_probes_are_not_vacuous() -> None:
    """A probe that matches nothing is indistinguishable from no probe.

    Rows 45 and 46 are the ones that were graded `I` for three releases while
    claiming judge machinery that has never existed. The patterns must match
    them, or regrading either row back to `I` would slip through unnoticed.
    """
    by_num = {num: capability for num, capability, _, _ in _rows()}
    judge_pattern = _CLAIM_PROBES["judge"][0]
    assert judge_pattern.search(by_num[45]), "the judge probe no longer matches row 45"
    assert judge_pattern.search(by_num[46]), "the judge probe no longer matches row 46"
    # ...and it must not match the row that claims independence *from* a judge.
    assert not judge_pattern.search(by_num[44]), (
        "row 44 claims judge-independent scoring; shipping no judge is evidence "
        "for that row, not against it"
    )


def test_probed_capabilities_really_are_absent() -> None:
    """If a judge ever ships, this test fails and the probe must be retired."""
    for name, (_, ships) in _CLAIM_PROBES.items():
        assert not ships(), (
            f"an implementation of {name!r} now exists; remove its claim probe and "
            "regrade the rows it was guarding"
        )
