"""Publication gate: fail if likely secrets appear in tracked files.

Scans the repository (excluding results/, web/node_modules, .git) for
high-confidence secret patterns: API keys, bearer tokens, AWS keys,
private keys, generic credential assignments. Exit 1 on any finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".tooltrace", "dist"}
SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".ico", ".woff2"}

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]{32,}")),
    ("openai-style-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github-pat", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    (
        "credential-assignment",
        re.compile(
            r"""(?i)(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*"""
            r"""["'][^"']{12,}["']"""
        ),
    ),
]

ALLOW_SUBSTRINGS = [
    "example",
    "placeholder",
    "your-api-key",
    "<key>",
    "dummy",
    "test-key",
    "xxxx",
    "redacted",
    "${",
    "{{",
]


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for name, pattern in PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0)
                low = snippet.lower()
                if any(a in low for a in ALLOW_SUBSTRINGS):
                    continue
                line_no = text.count(chr(10), 0, match.start()) + 1
                findings.append(f"{rel}:{line_no}: {name}")
    if findings:
        print("LIKELY SECRETS DETECTED — publication blocked:", file=sys.stderr)
        for f in findings:
            print(f"  {f}", file=sys.stderr)
        return 1
    print(f"secret scan clean ({len(list(ROOT.rglob('*')))} paths considered)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
