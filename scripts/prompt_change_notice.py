#!/usr/bin/env python3
"""Say out loud when a change alters what an agent is shown.

A prompt is code, and it is the one kind of code that passes ruff, mypy and the
entire test suite while silently invalidating every baseline in the repository.
Change the system prompt or a tool description and yesterday's success rate is
no longer comparable to today's -- not because the agent got better or worse, but
because it was asked a different question.

This does **not** block the commit, and that is deliberate. A hook that refuses
a legitimate prompt improvement gets removed within a week, and then nobody is
told about the next one either. It prints what changed and what that means for
the numbers, and exits 0.

What it looks at:

- the system prompt template, which every HTTP adapter shares;
- the tool catalogue renderer, which decides what a model is told a tool takes;
- any tool's `description` or `parameters`, which is the text and the schema a
  model reads before deciding to call it.

Run by pre-commit on the files that carry those. Called directly it takes file
paths as arguments, so it can be used from any hook system.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Assignments whose right-hand side is text a model reads.
WATCHED = (
    ("SYSTEM_PROMPT", "the system prompt every HTTP adapter sends"),
    ("description", "a tool description, which a model reads as documentation"),
    ("parameters", "a tool's argument schema, which decides what a model may send"),
    ("HISTORY_TURNS", "how much conversation a model is shown"),
)


def changed_lines(path: Path) -> list[str]:
    """Added and removed lines for one staged file, or [] when git cannot say."""
    try:
        diff = subprocess.run(
            ["git", "diff", "--cached", "--unified=0", "--", str(path)],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
    except OSError:
        return []
    if diff.returncode != 0:
        return []
    return [
        line
        for line in diff.stdout.splitlines()
        if (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---"))
    ]


def findings(paths: list[Path]) -> list[str]:
    notes: list[str] = []
    for path in paths:
        lines = changed_lines(path)
        if not lines:
            continue
        body = "\n".join(lines)
        for token, meaning in WATCHED:
            # Word-boundary rather than substring: `description` matching inside
            # `descriptions_by_name` would fire on edits that change nothing a
            # model sees, and a hook that cries wolf is a hook that gets removed.
            if re.search(rf"^[+-].*\b{re.escape(token)}\b\s*[:=]", body, re.MULTILINE):
                notes.append(f"{path.relative_to(ROOT) if path.is_absolute() else path}: {meaning}")
                break
    return notes


def main(argv: list[str]) -> int:
    paths = [Path(arg) for arg in argv[1:]]
    if not paths:
        return 0
    notes = findings(paths)
    if not notes:
        return 0

    print("This change alters what an agent is shown:")
    for note in sorted(set(notes)):
        print(f"  - {note}")
    print()
    print(
        "Recorded baselines are no longer comparable to runs made after it. The agent "
        "was not asked the same question, so a difference in the numbers is not a "
        "difference in the agent."
    )
    print("Re-record a baseline before reading a comparison:  tooltrace baseline --name ...")
    # Never blocks. A hook that refuses a legitimate prompt improvement is
    # removed within the week, and then nobody hears about the next one either.
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main(sys.argv))
