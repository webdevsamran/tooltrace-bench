"""Workspace snapshotting and unified diffing."""

from __future__ import annotations

import difflib
from pathlib import Path

SKIP_DIRS = {"__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def snapshot(workspace: Path) -> dict[str, str]:
    """Return {relative path: content} for all text files under *workspace*."""
    files: dict[str, str] = {}
    for f in sorted(workspace.rglob("*")):
        if not f.is_file():
            continue
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        rel = f.relative_to(workspace).as_posix()
        try:
            files[rel] = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            files[rel] = "<binary or unreadable>"
    return files


def workspace_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Unified diff between two snapshots (stable ordering)."""
    lines: list[str] = []
    all_paths = sorted(set(before) | set(after))
    for path in all_paths:
        old = before.get(path)
        new = after.get(path)
        if old == new:
            continue
        if old is None:
            lines.extend(f"--- /dev/null{chr(10)}+++ {path}")
            lines.extend(f"+{line}" for line in new.splitlines())  # type: ignore[union-attr]
            lines.append("")
        elif new is None:
            lines.extend(f"--- {path}{chr(10)}+++ /dev/null")
            lines.extend(f"-{line}" for line in old.splitlines())
            lines.append("")
        else:
            diff = difflib.unified_diff(
                old.splitlines(),
                new.splitlines(),
                fromfile=path,
                tofile=path,
                lineterm="",
            )
            lines.extend(diff)
            lines.append("")
    return chr(10).join(lines).strip()


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
