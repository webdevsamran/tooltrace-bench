"""Run every task's reference solution through the real runner; print PASS/FAIL."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.tasks import load_all_tasks
from tooltrace.tasks.sdk import test_task


def main() -> int:
    failures = 0
    lines = []
    for t in load_all_tasks():
        problems = test_task(t)
        status = "PASS" if not problems else "FAIL"
        if problems:
            failures += 1
        line = f"{status} {t.id}"
        if problems:
            line += " | " + "; ".join(problems[:2])
        lines.append(line)
    report = chr(10).join(lines)
    print(report)
    out = Path(__file__).resolve().parents[1] / "results" / "_refcheck.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text(report + chr(10), encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
