"""Would the candidate have made the same decisions on this production trace?

Shadow mode usually means running a candidate against live traffic and
comparing outcomes. **That is not possible here and the difference matters.** A
production trace happened against real systems holding real state at a
particular moment; re-running a candidate in a temp workspace is not that
environment. It is a different task that happens to share an objective, and any
"outcome" it produces is an outcome in a sandbox rather than a prediction about
production.

So this compares **decisions**, which is what a team can actually learn from a
replayed trace: given the same objective, does the candidate reach for the same
tools, on the same resources, in the same order -- and where does it first stop
doing so?

## What a divergence is and is not

A divergence is not a defect. The candidate may be doing something better, and
the recorded run is a log rather than an oracle: production is where mistakes
happen. What the report gives is a *place to look*, ranked by how early it is,
because everything before the first divergence is common ground.

The alignment is a longest-common-subsequence diff over a per-step signature,
identical in shape to the dashboard's. `tests/fixtures/trace_alignment.json`
holds the cases both implementations are checked against, so the Python and
TypeScript versions cannot drift into disagreeing about what "the same
decision" means.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

BOTH = "both"
RECORDED_ONLY = "recorded_only"
CANDIDATE_ONLY = "candidate_only"


@dataclass(frozen=True)
class Step:
    """One decision, reduced to what makes two of them comparable."""

    tool: str
    resource: str

    @property
    def signature(self) -> str:
        return f"{self.tool}:{self.resource}"


#: Argument names that identify the thing a call acts on, most specific first.
#: A signature over *all* arguments would push two writes to one path into two
#: unrelated rows, hiding the difference in content that is the interesting part.
RESOURCE_ARGS = ("path", "url", "file", "target", "name", "command")


def _resource(args: dict[str, Any]) -> str:
    for key in RESOURCE_ARGS:
        value = args.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def steps_from_events(events: list[Any]) -> list[Step]:
    """Decisions from a trace, ignoring everything that is not one."""
    steps: list[Step] = []
    for event in events:
        kind = getattr(event, "type", None)
        payload = getattr(event, "payload", None)
        if kind is None and isinstance(event, dict):
            kind = event.get("type")
            payload = event.get("payload")
        if kind != "tool_request":
            continue
        payload = payload or {}
        tool = payload.get("tool")
        if not isinstance(tool, str) or not tool:
            continue
        args = payload.get("args")
        steps.append(Step(tool=tool, resource=_resource(args if isinstance(args, dict) else {})))
    return steps


def align(recorded: list[Step], candidate: list[Step]) -> list[dict[str, Any]]:
    """Pair up the two sequences so the same decision lands on the same row.

    A positional zip goes out of register at the first extra call, after which
    every row compares unrelated steps while looking like a comparison. Both
    traces are tens of steps long, so the quadratic table costs nothing and
    avoids a dependency in a project that deliberately has none.
    """
    a = [s.signature for s in recorded]
    b = [s.signature for s in candidate]
    table = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) - 1, -1, -1):
        for j in range(len(b) - 1, -1, -1):
            table[i][j] = (
                table[i + 1][j + 1] + 1 if a[i] == b[j] else max(table[i + 1][j], table[i][j + 1])
            )

    rows: list[dict[str, Any]] = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            rows.append({"side": BOTH, "recorded": recorded[i], "candidate": candidate[j]})
            i += 1
            j += 1
        elif table[i + 1][j] >= table[i][j + 1]:
            rows.append({"side": RECORDED_ONLY, "recorded": recorded[i], "candidate": None})
            i += 1
        else:
            rows.append({"side": CANDIDATE_ONLY, "recorded": None, "candidate": candidate[j]})
            j += 1
    while i < len(a):
        rows.append({"side": RECORDED_ONLY, "recorded": recorded[i], "candidate": None})
        i += 1
    while j < len(b):
        rows.append({"side": CANDIDATE_ONLY, "recorded": None, "candidate": candidate[j]})
        j += 1
    return rows


def shadow_report(recorded_events: list[Any], candidate_events: list[Any]) -> dict[str, Any]:
    """Where a candidate stopped agreeing with a recorded run, and what that is worth."""
    recorded = steps_from_events(recorded_events)
    candidate = steps_from_events(candidate_events)
    rows = align(recorded, candidate)

    shared = sum(1 for row in rows if row["side"] == BOTH)
    only_recorded = [row for row in rows if row["side"] == RECORDED_ONLY]
    only_candidate = [row for row in rows if row["side"] == CANDIDATE_ONLY]
    diverged_at = next((index for index, row in enumerate(rows) if row["side"] != BOTH), None)

    return {
        "recorded_steps": len(recorded),
        "candidate_steps": len(candidate),
        "shared_steps": shared,
        "diverged_at": diverged_at,
        "only_in_recorded": [
            {"tool": row["recorded"].tool, "resource": row["recorded"].resource}
            for row in only_recorded
        ],
        "only_in_candidate": [
            {"tool": row["candidate"].tool, "resource": row["candidate"].resource}
            for row in only_candidate
        ],
        "rows": [
            {
                "side": row["side"],
                "recorded": (
                    {"tool": row["recorded"].tool, "resource": row["recorded"].resource}
                    if row["recorded"]
                    else None
                ),
                "candidate": (
                    {"tool": row["candidate"].tool, "resource": row["candidate"].resource}
                    if row["candidate"]
                    else None
                ),
            }
            for row in rows
        ],
        "statement": (
            f"the candidate matched the recorded run for {shared} step(s)"
            + (
                ". It never diverged."
                if diverged_at is None
                else f", then diverged at step {diverged_at + 1}."
            )
        ),
        # Both limits travel with the numbers, because either one alone would be
        # read as a stronger claim than this makes.
        "outcomes_not_compared": (
            "This compares decisions, not outcomes. The recorded run happened against real "
            "systems holding real state; the candidate ran in a temp workspace, which is a "
            "different task sharing an objective. Any outcome here is an outcome in a "
            "sandbox rather than a prediction about production."
        ),
        "divergence_is_not_a_defect": (
            "A divergence is a place to look, not a fault. The candidate may be doing "
            "something better, and the recorded run is a log rather than an oracle -- "
            "production is where the mistakes happened in the first place."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "### Shadow comparison",
        "",
        report["statement"],
        "",
        "| # | Recorded | Candidate |",
        "|---|---|---|",
    ]
    for index, row in enumerate(report["rows"], start=1):
        recorded = row["recorded"]
        candidate = row["candidate"]
        left = f"`{recorded['tool']}` {recorded['resource']}".strip() if recorded else "—"
        right = f"`{candidate['tool']}` {candidate['resource']}".strip() if candidate else "—"
        lines.append(f"| {index} | {left} | {right} |")
    lines += [
        "",
        f"*{report['outcomes_not_compared']}*",
        "",
        f"*{report['divergence_is_not_a_defect']}*",
        "",
    ]
    return "\n".join(lines)
