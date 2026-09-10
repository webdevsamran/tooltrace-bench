"""Turn a production failure into a regression task.

`tooltrace ingest` converts a production trace — Claude Code, Copilot, Codex,
anything emitting OTel GenAI spans — into this project's event format, and
`score_trace_only` scores what a trajectory alone can answer. Both stop one step
short of the thing anyone actually wants after an incident: *make sure this never
happens again*.

That step is turning the failure into a task. A trace records what the agent did;
a task records what it should have done, in a form that runs on every future
candidate. Deriving the second from the first is mechanical for exactly one
class of assertion — the trajectory — and impossible for the rest, and this
module is careful about which is which.

**What it can generate.** The tools the agent called, in order, with their
argument shapes. Whether calls failed. That is genuinely useful: a large share of
production agent failures are trajectory failures — the wrong tool, in the wrong
order, or one that errored and was never retried.

**What it refuses to generate.** A workspace, an expected output, or a
correctness assertion. A production trace does not contain the filesystem it ran
against, and a task with an invented workspace would test the invention. The
generated task ships with those sections empty and a `TODO` naming each one,
because a task that looks complete and tests nothing is worse than an obviously
unfinished one.

**And it never claims the generated task reproduces the incident.** It encodes
the trajectory the incident had. Whether that trajectory is *why* it failed is a
judgement the person who saw the incident makes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tooltrace.core.models import TraceEvent

#: A generated task is a draft. This marker is in the id, the objective and the
#: metadata, so a draft cannot quietly become part of a published suite.
DRAFT_MARKER = "draft"


def _paired_calls(events: Sequence[TraceEvent]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for event in events:
        payload = dict(event.payload or {})
        if event.type in ("tool_request", "tool_call"):
            pending = {
                "tool": str(payload.get("tool") or ""),
                "args": payload.get("args") or {},
                "status": None,
            }
        elif event.type == "tool_result" and pending is not None:
            pending["status"] = payload.get("status")
            calls.append(pending)
            pending = None
    if pending is not None:
        pending["status"] = "no_result"
        calls.append(pending)
    return calls


def _arg_shape(args: dict[str, Any]) -> dict[str, str]:
    """Argument *types*, not values.

    A generated assertion that pinned the exact paths from one incident would
    only ever match that incident. `tool_call_match` compares shapes, which is
    what makes the task useful against a future candidate.
    """
    shapes: dict[str, str] = {}
    for key, value in (args or {}).items():
        if isinstance(value, bool):
            shapes[str(key)] = "boolean"
        elif isinstance(value, int | float):
            shapes[str(key)] = "number"
        elif isinstance(value, list):
            shapes[str(key)] = "array"
        elif isinstance(value, dict):
            shapes[str(key)] = "object"
        else:
            shapes[str(key)] = "string"
    return shapes


def promote_trace(
    events: Sequence[TraceEvent],
    *,
    task_id: str,
    objective: str = "",
    incident: str = "",
) -> dict[str, Any]:
    """A draft regression task encoding the trajectory this trace took.

    Every section that cannot be derived is present and empty, with a `TODO`
    naming what a human has to supply. A generated task that *looked* finished
    would be the worst possible output here: it would run, pass, and test
    nothing.
    """
    calls = _paired_calls(events)
    tools = sorted({c["tool"] for c in calls if c["tool"]})
    failed = [c for c in calls if c["status"] not in (None, "ok")]

    todos: list[str] = [
        "starting_workspace: a production trace does not contain the filesystem it ran "
        "against. Add the files this task should start from.",
        "assertions: add at least one correctness assertion. The generated ones check the "
        "trajectory only, and a task with no correctness check passes for an agent that "
        "did nothing useful.",
    ]

    assertions: list[dict[str, Any]] = []
    if calls:
        assertions.append(
            {
                "type": "tool_call_match",
                "params": {
                    "ordered": True,
                    "expected": [
                        {"tool": c["tool"], "args": _arg_shape(c["args"])}
                        for c in calls
                        if c["tool"]
                    ],
                },
                "weight": 1.0,
                "description": "the trajectory the incident took",
            }
        )
    if tools:
        assertions.append(
            {
                "type": "tools_used",
                "params": {"required": tools},
                "weight": 1.0,
                "description": "every tool the incident used",
            }
        )
    if failed:
        # Only when the incident actually had failures. Generating "no failed
        # calls" for a trace that had none would assert something the incident
        # never demonstrated.
        assertions.append(
            {
                "type": "no_failed_calls",
                "params": {"allow": 0},
                "weight": 1.0,
                "description": (
                    f"the incident had {len(failed)} failed call(s); a fix should have none"
                ),
            }
        )

    return {
        "id": f"{task_id}-{DRAFT_MARKER}",
        "version": "0.1.0",
        "category": "regression",
        "difficulty": "medium",
        "objective": objective
        or f"TODO: describe what the agent should have done. Derived from incident {incident or '(unnamed)'}.",
        "max_steps": max(len(calls) * 2, 4),
        "allowed_tools": tools,
        "network_policy": "disabled",
        "starting_workspace": {},
        "assertions": assertions,
        "metadata": {
            "generated_from": "production_trace",
            "incident": incident,
            "observed_calls": len(calls),
            "observed_failures": len(failed),
            "todos": todos,
            # The claim this module will not make.
            "note": (
                "This task encodes the trajectory the incident took. Whether that "
                "trajectory is *why* it failed is a judgement for whoever saw the "
                "incident; nothing here establishes it."
            ),
        },
    }


def readiness(task: dict[str, Any]) -> dict[str, Any]:
    """Is this draft finished enough to add to a suite?

    A generated task always fails this until a human has filled in what could
    not be derived. That is the intended state, and saying it plainly is what
    stops a draft drifting into a published pack.
    """
    problems: list[str] = []
    if not task.get("starting_workspace"):
        problems.append("no starting workspace: this task runs against an empty directory")

    assertion_types = {str(a.get("type")) for a in task.get("assertions") or []}
    trajectory_only = {"tool_call_match", "tools_used", "no_failed_calls", "tool_call_count"}
    if assertion_types and assertion_types <= trajectory_only:
        problems.append(
            "every assertion is about the trajectory: an agent that made the right calls "
            "and produced the wrong result would pass"
        )
    if not assertion_types:
        problems.append("no assertions at all")
    if str(task.get("objective", "")).startswith("TODO"):
        problems.append("the objective is still a placeholder")
    if DRAFT_MARKER in str(task.get("id", "")):
        problems.append(
            f"the id still carries the '{DRAFT_MARKER}' marker; rename it when it is finished"
        )

    return {
        "ready": not problems,
        "problems": problems,
        "statement": (
            "A generated task is a draft. It encodes what the incident did, not what "
            "correct behaviour is, and only a person who saw the incident can supply the "
            "second."
        ),
    }
