"""Repository/publication secret scanner.

Usage:
    python -m tooltrace.security.scan_repo [paths...]

Scans text files for likely secrets and exits non-zero when any are found.
Used by pre-commit and CI as a publication gate. Binary files and common
vendor/lock directories are skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tooltrace.security.sanitize import find_secrets

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
    "web/dist",
}

TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".cfg",
    ".ini",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".html",
    ".css",
    ".csv",
    ".sql",
    ".cff",
    ".xml",
}


def _iter_files(paths: list[Path]):
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not any(part in SKIP_DIRS for part in f.parts):
                    yield f
        elif p.is_file():
            yield p


def scan(paths: list[Path]) -> list[tuple[Path, str, int]]:
    """Return (file, label, line) findings."""
    findings: list[tuple[Path, str, int]] = []
    for f in _iter_files(paths):
        if f.suffix.lower() not in TEXT_SUFFIXES and f.name not in {
            "LICENSE",
            "NOTICE",
            "AUTHORS",
            "MAINTAINERS",
            "CODEOWNERS",
            "Dockerfile",
            ".gitignore",
        }:
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            for finding in find_secrets(line):
                findings.append((f, finding.label, i))
    return findings


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    roots = [Path(a) for a in args] or [Path(".")]
    findings = scan(roots)
    if findings:
        print("LIKELY SECRETS DETECTED — publication blocked:")
        for path, label, lineno in findings:
            print(f"  {path}:{lineno}: {label}")
        print(f"{len(findings)} finding(s). Remove or redact before committing.")
        return 9
    print("No likely secrets detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
