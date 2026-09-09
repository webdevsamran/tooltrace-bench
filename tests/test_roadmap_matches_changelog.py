"""The roadmap and the changelog must agree about what has shipped.

`ROADMAP.md` headed a section "v0.3 — Ecosystem (planned)" while
`pyproject.toml` was at 0.3.0 and `CHANGELOG.md` carried a shipped `[0.3.0]`
entry dated 2026-09-07. A reader arriving at the roadmap would conclude the
release had not happened. Nothing recorded what 0.3.0 actually delivered.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ROADMAP = (_ROOT / "ROADMAP.md").read_text(encoding="utf-8")
_CHANGELOG = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

#: `## v0.3 — Ecosystem (shipped 2026-09-07)` -> ("0.3", "Ecosystem …(shipped …)")
_HEADING = re.compile(r"^##\s+v(\d+\.\d+)\s*(?:—|-)?\s*(.*)$", re.M)
#: `## [0.3.0] — Ecosystem, adoption and integrity pass (2026-09-07)`
_RELEASED = re.compile(r"^##\s+\[(\d+\.\d+)\.\d+\]", re.M)


def _released_minors() -> set[str]:
    return set(_RELEASED.findall(_CHANGELOG))


def test_no_released_version_is_still_labelled_planned() -> None:
    released = _released_minors()
    offenders = [
        f"v{minor} is labelled '{rest.strip()}' but CHANGELOG.md has a released {minor}.x entry"
        for minor, rest in _HEADING.findall(_ROADMAP)
        if minor in released and "planned" in rest.lower()
    ]
    assert not offenders, "; ".join(offenders)


def test_every_shipped_heading_has_a_changelog_entry() -> None:
    released = _released_minors()
    offenders = [
        f"v{minor} claims to have shipped but CHANGELOG.md has no {minor}.x entry"
        for minor, rest in _HEADING.findall(_ROADMAP)
        if "shipped" in rest.lower() and minor not in released
    ]
    assert not offenders, "; ".join(offenders)


def test_the_current_version_has_a_roadmap_section() -> None:
    from tooltrace.core.versions import FRAMEWORK_VERSION

    minor = ".".join(FRAMEWORK_VERSION.split(".")[:2])
    headings = {m for m, _ in _HEADING.findall(_ROADMAP)}
    assert minor in headings, (
        f"the shipped version is {FRAMEWORK_VERSION} but ROADMAP.md has no v{minor} section"
    )
