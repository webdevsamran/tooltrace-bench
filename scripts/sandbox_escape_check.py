"""Try to break out of the sandbox, and fail the build if anything does.

`scripts/sandbox_check.py` is a conformance check: it calls
`resolve_in_workspace` with bad paths and verifies some defaults. That proves a
helper rejects what it is handed. It does not prove an agent cannot get out,
because an agent never calls that helper -- it calls tools, through
`ToolExecutor`.

This runs sixteen escape attempts through that real path: traversal and absolute
paths across every filesystem tool, network egress while the policy is disabled,
metadata-endpoint access, and remote git operations. Success is judged on
evidence -- a file appearing outside the workspace -- rather than on the tool's
own report, because a write that claims to have failed and still landed outside
has still escaped.

Two documented limits of the *local* sandbox are attempted too and reported
rather than skipped: `shell` can write outside the workspace and read the
environment, because blocking that needs kernel-level isolation, which is what
the Docker provider is for. A suite that quietly omits the attacks it would fail
measures nothing.

    python scripts/sandbox_escape_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.sandbox.escape import check_isolation


def main() -> int:
    report = check_isolation()

    for result in report["results"]:
        mark = "ESCAPED" if result["escaped"] else "blocked"
        if result["escaped"] and result["severity"] == "known_limit":
            mark = "escaped (known limit)"
        print(f"  [{mark:>21}] {result['name']}")

    print(
        f"\nsandbox escape suite: {report['attempts']} attempts, "
        f"{len(report['breaches'])} breach(es), "
        f"{len(report['known_limits_confirmed'])} documented limit(s) confirmed"
    )

    if report["known_limits_now_blocked"]:
        # Good news: tighten docs/threat-model.md rather than leave it
        # overstating what an attacker can do.
        print(
            "note: these documented limits are now blocked -- consider tightening "
            f"docs/threat-model.md: {report['known_limits_now_blocked']}"
        )

    if not report["ok"]:
        print("\nFAIL: the sandbox boundary was broken", file=sys.stderr)
        print(json.dumps(report["breaches"], indent=2), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
