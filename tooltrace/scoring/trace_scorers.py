"""Structural scoring of the tool calls an agent actually made.

The Berkeley Function-Calling Leaderboard grades a model by matching an emitted
call against an expected signature structurally — function name, argument
names, argument types — without executing anything. That technique is a good
one, it is the de-facto standard for the question "did it call the tool
correctly", and it is worth adopting rather than competing with. The scorers
here are modelled on it, with attribution.

What it is **not** is the same measurement as this project's. BFCL scores the
call; a trajectory score asks whether the run worked — whether the agent
recovered, what it changed, what it cost. An agent can emit every call perfectly
and still leave the workspace wrong, and an agent can fumble a call and recover
cleanly. `docs/tool-call-structure.md` states that distinction so a reader
arriving from the model-evaluation side is not misled about what this number
means, and so it never becomes the headline metric here.

These are registered as **trace scorers**, a second scorer kind: the existing
fifteen take `(params, workspace)` and cannot see a trajectory at all.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tooltrace.scoring.base import ScorerOutcome
from tooltrace.scoring.trace_view import ToolCall, TraceView

#: name -> trace scorer. Kept separate from `scorer_registry` because the
#: signatures differ; `score_task` dispatches on membership.
TRACE_SCORERS: dict[str, Callable[[dict[str, Any], TraceView], ScorerOutcome]] = {}


def register_trace_scorer(
    name: str,
) -> Callable[
    [Callable[[dict[str, Any], TraceView], ScorerOutcome]],
    Callable[[dict[str, Any], TraceView], ScorerOutcome],
]:
    def decorator(
        fn: Callable[[dict[str, Any], TraceView], ScorerOutcome],
    ) -> Callable[[dict[str, Any], TraceView], ScorerOutcome]:
        TRACE_SCORERS[name] = fn
        return fn

    return decorator


#: JSON-ish type names, so an expectation can say `{"path": "string"}` without
#: the task author needing to know Python's type names.
_TYPE_NAMES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _type_matches(value: Any, expected: str) -> bool:
    types = _TYPE_NAMES.get(expected.lower())
    if types is None:
        return False
    # bool is a subclass of int; "integer" should not silently accept True.
    if expected.lower() in {"number", "integer"} and isinstance(value, bool):
        return False
    return isinstance(value, types)


def match_call(call: ToolCall, expected: dict[str, Any]) -> list[str]:
    """Structural comparison of one call against one expectation.

    Returns the reasons it does not match, empty when it does. Nothing is
    executed: this reads the recorded request only.
    """
    problems: list[str] = []

    want_tool = expected.get("tool")
    if want_tool and call.tool != want_tool:
        return [f"expected tool {want_tool!r}, got {call.tool!r}"]

    required = expected.get("args") or {}
    if isinstance(required, list):
        # A bare list means "these argument names must be present".
        missing = [name for name in required if name not in call.args]
        if missing:
            problems.append(f"missing arguments {sorted(missing)}")
        return problems

    for name, constraint in required.items():
        if name not in call.args:
            problems.append(f"missing argument {name!r}")
            continue
        value = call.args[name]
        if isinstance(constraint, str) and constraint.lower() in _TYPE_NAMES:
            if not _type_matches(value, constraint):
                problems.append(
                    f"argument {name!r} should be {constraint}, got {type(value).__name__}"
                )
        elif isinstance(constraint, dict) and "type" in constraint:
            if not _type_matches(value, str(constraint["type"])):
                problems.append(
                    f"argument {name!r} should be {constraint['type']}, got {type(value).__name__}"
                )
            if "equals" in constraint and value != constraint["equals"]:
                problems.append(f"argument {name!r} should equal {constraint['equals']!r}")
        elif value != constraint:
            problems.append(f"argument {name!r} should equal {constraint!r}, got {value!r}")

    forbidden = expected.get("forbidden_args") or []
    present = [name for name in forbidden if name in call.args]
    if present:
        problems.append(f"forbidden arguments present: {sorted(present)}")

    return problems


@register_trace_scorer("tool_call_match")
def _tool_call_match(params: dict[str, Any], trace: TraceView) -> ScorerOutcome:
    """Score whether the expected calls appear, structurally, in order.

    params:
      expected: [{tool, args: {name: "string"| {type, equals}} , forbidden_args: []}]
      ordered:  bool, default True -- expectations must match in sequence
      allow_extra: bool, default True -- other calls may also appear
    """
    expectations = params.get("expected") or []
    if not isinstance(expectations, list) or not expectations:
        return ScorerOutcome(0.0, "no expected calls declared")

    ordered = bool(params.get("ordered", True))
    allow_extra = bool(params.get("allow_extra", True))
    calls = list(trace.calls)

    matched = 0
    reasons: list[str] = []
    cursor = 0
    for index, expected in enumerate(expectations):
        search = calls[cursor:] if ordered else calls
        for offset, call in enumerate(search):
            if not match_call(call, expected):
                matched += 1
                if ordered:
                    cursor += offset + 1
                break
        else:
            nearest = [c for c in calls if c.tool == expected.get("tool")]
            why = (
                "; ".join(match_call(nearest[0], expected))
                if nearest
                else f"no call to {expected.get('tool')!r}"
            )
            reasons.append(f"expectation {index}: {why}")

    if not allow_extra and len(calls) > len(expectations):
        extra = [c.tool for c in calls[len(expectations) :]]
        reasons.append(f"unexpected extra calls: {extra}")
        return ScorerOutcome(0.0, "; ".join(reasons))

    score = matched / len(expectations)
    detail = (
        f"matched {matched}/{len(expectations)} expected calls"
        if not reasons
        else f"matched {matched}/{len(expectations)}: " + "; ".join(reasons[:3])
    )
    return ScorerOutcome(round(score, 6), detail)


@register_trace_scorer("tools_used")
def _tools_used(params: dict[str, Any], trace: TraceView) -> ScorerOutcome:
    """Which tools were used, regardless of arguments or order.

    params: required: [names], forbidden: [names]
    """
    used = set(trace.tools_used())
    required = set(params.get("required") or [])
    forbidden = set(params.get("forbidden") or [])

    missing = sorted(required - used)
    trespass = sorted(forbidden & used)
    if missing or trespass:
        parts = []
        if missing:
            parts.append(f"never called {missing}")
        if trespass:
            parts.append(f"called forbidden {trespass}")
        return ScorerOutcome(0.0, "; ".join(parts))
    return ScorerOutcome(1.0, f"used {sorted(used)}")


@register_trace_scorer("no_failed_calls")
def _no_failed_calls(params: dict[str, Any], trace: TraceView) -> ScorerOutcome:
    """Full marks only when every tool call succeeded.

    params: allow: int, default 0 -- tolerated failures (a recovery task may
    legitimately expect some).
    """
    allowed = int(params.get("allow", 0))
    failed = [c for c in trace.calls if not c.ok]
    if len(failed) <= allowed:
        return ScorerOutcome(1.0, f"{len(failed)} failed call(s), {allowed} allowed")
    detail = ", ".join(f"{c.tool}@{c.seq}: {c.status}" for c in failed[:3])
    return ScorerOutcome(0.0, f"{len(failed)} failed call(s) (allowed {allowed}): {detail}")
