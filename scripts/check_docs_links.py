"""Check relative markdown links across documentation.

Fails (exit 1) when a relative link target does not exist. External
http(s) links and in-page anchors are skipped. Run in CI so docs never
silently rot.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_FILES = ["README.md", "ARCHITECTURE.md", "ROADMAP.md", "CONTRIBUTING.md",
              "SECURITY.md", "PRODUCT_GAPS.md", "DIFFERENTIATORS.md"]
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def iter_docs() -> list[Path]:
    paths = [ROOT / name for name in SCAN_FILES if (ROOT / name).exists()]
    paths.extend(sorted((ROOT / "docs").glob("*.md")))
    return paths


def main() -> int:
    broken: list[str] = []
    checked = 0
    for path in iter_docs():
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            checked += 1
            clean = target.split("#", 1)[0]
            if not clean:
                continue  # pure in-page anchor
            resolved = (path.parent / clean).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    print(f"docs link check: {checked} relative links checked, {len(broken)} broken")
    for b in broken:
        print(f"  BROKEN: {b}")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
