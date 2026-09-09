"""Every code path a document cites must resolve.

`docs/feature-status.md` had a path checker; nothing else did. So
`docs/differentiators.md` -- the file whose whole job is to say what this
project does that others do not -- cited four modules that do not exist
(`metrics/recovery.py`, `metrics/sideeffects.py`, `perturbations.py`, and
`scoring/judges.py`, which describes a capability that has never existed).
`scripts/check_docs_links.py` did not catch them because it validates markdown
`[](...)` links, not backticked paths.

The resolver lives here rather than in the test so there is one implementation
with two consumers: this script (a CI step over every document) and
`tests/test_feature_status_is_truthful.py` (which additionally enforces the
grading rules of that one table).

    python scripts/check_doc_code_refs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Documents whose backticked paths must resolve.
DOCS: tuple[str, ...] = (
    "README.md",
    "ARCHITECTURE.md",
    "ROADMAP.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "AGENTS.md",
)

#: Where a bare path in a document may be rooted. The tables write
#: `packs/git-workflow` for what is really `tooltrace/tasks/packs/git-workflow`.
BASES: tuple[str, ...] = ("", "tooltrace/", "tooltrace/tasks/", "scripts/", "docs/", "web/src/")

#: A backticked token is treated as a repository path only when it carries a
#: directory separator *and* a known extension (or names a directory). That is
#: deliberately narrow. A looser rule flags bundle member names (`result.json`,
#: `trace.jsonl`), branch names (`feat/my-task-pack`), task ids
#: (`fileops/copy-and-rename`), purl prefixes (`pkg:pypi/`) and grades (`I/P`) --
#: and a checker that cries wolf is one people learn to ignore, which is worse
#: than not having it.
PATH_SUFFIXES: tuple[str, ...] = (
    ".py",
    ".json",
    ".jsonl",
    ".yaml",
    ".yml",
    ".md",
    ".toml",
    ".cff",
    ".ts",
    ".tsx",
    ".css",
)

#: Placeholder syntax: a token containing any of these is a template, not a path.
PLACEHOLDERS: tuple[str, ...] = ("*", "<", ">", "{", "}", "$")

#: Paths that exist inside a sandbox workspace at run time and never in the
#: repository. This checker verifies *repository* paths; a runtime path is a
#: different category, and declaring it here is honest, whereas silently
#: widening `looks_like_path` until nothing fails would not be.
RUNTIME_PREFIXES: tuple[str, ...] = (".tooltrace_egress/",)


def looks_like_path(token: str) -> bool:
    raw = token.strip()
    if not raw or " " in raw:
        return False
    if raw.startswith(("http://", "https://", "/")):
        return False  # URLs and API routes are not files
    if ":" in raw:
        return False  # a URI scheme or purl prefix such as `pkg:pypi/`
    if any(ch in raw for ch in PLACEHOLDERS):
        return False
    if "/" not in raw:
        return False
    if raw.startswith(RUNTIME_PREFIXES):
        return False  # created inside a workspace at run time, not in the repo
    return raw.endswith(PATH_SUFFIXES) or raw.endswith("/")


def strip_uncheckable(text: str) -> str:
    """Drop fenced code blocks and blockquotes before looking for citations.

    Fenced blocks hold commands, whose paths are covered by
    `tests/test_readme_is_truthful.py` and `scripts/check_docs_links.py`.

    Blockquotes hold the dated correction notes, which exist precisely to say
    "this row used to cite `analysis.py`, which is a package now". A correction
    is prose about history; treating its examples as live citations would make
    it impossible to write one down.
    """
    kept: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or stripped.startswith(">"):
            continue
        kept.append(line)
    return chr(10).join(kept)


def resolves(token: str) -> bool:
    """True when `token` names something on disk."""
    raw = token.strip().rstrip(",;:")
    # `removeprefix`, not `lstrip("./")`: lstrip strips *characters*, so it ate
    # the leading dot of every dotfile and `.tooltrace-baselines.json` silently
    # became `tooltrace-baselines.json`, which resolves to nothing and was never
    # reported because the token was not considered a path in the first place.
    candidate = raw.removeprefix("./")
    for base in BASES:
        full = base + candidate
        if "*" in full:
            if list(ROOT.glob(full)):
                return True
        elif (ROOT / full).exists():
            return True
    if "/" not in candidate and candidate.endswith(".py"):
        return bool(list((ROOT / "tooltrace").rglob(candidate)))
    return False


def iter_refs(text: str) -> list[str]:
    """Backticked tokens in `text` that look like repository paths."""
    return [token for token in re.findall(r"`([^`\n]+)`", text) if looks_like_path(token)]


def check_file(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path.name}: missing"]
    text = strip_uncheckable(path.read_text(encoding="utf-8"))
    return [
        f"{path.relative_to(ROOT).as_posix()}: `{token}` does not resolve"
        for token in iter_refs(text)
        if not resolves(token)
    ]


def documents() -> list[Path]:
    named = [ROOT / name for name in DOCS]
    return named + sorted((ROOT / "docs").glob("*.md"))


def main() -> int:
    problems: list[str] = []
    checked = 0
    for path in documents():
        if not path.is_file():
            continue
        checked += 1
        problems.extend(check_file(path))
    if problems:
        print(f"FAIL: {len(problems)} unresolved code reference(s)", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"doc code refs: {checked} documents checked, every cited path resolves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
