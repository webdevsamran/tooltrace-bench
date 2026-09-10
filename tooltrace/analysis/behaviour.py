"""Behaviour that a pass/fail score cannot see.

The Holistic Agent Leaderboard paper makes an observation this module exists to
act on: *agents with identical accuracy scores behave very differently*. Some
take costly shortcuts. Some recover from a failure in one step, some flounder for
five, and some "recover" into a wrong answer — and all three land in the same
`recovered: true` field.

Four questions, none of which the score answers:

- **Recovery quality** (F037): a fault was injected and the run passed. Did the
  agent fix it immediately, take five steps, or recover the tool call and still
  produce the wrong result?
- **Error propagation** (F033): did one failure cause the next three, or were
  they independent?
- **Shortcuts** (F035): did the agent do the task, or produce something that
  satisfies the assertions without doing the task?
- **Autonomy** (F034): how much human intervention did it need?

The shortcut detector is the one that needs care, and the rule it follows is
absolute: **it reports signals, never verdicts.** "Wrote the answer without ever
reading the input" is a fact about a trace. "The agent cheated" is an accusation,
and this module has no standing to make it — a task may legitimately be solvable
without reading anything. Every signal names what was observed and what would
have to be checked to conclude anything.

Autonomy is the one that must currently say "unmeasured". No shipping task
requires intervention and no adapter records one, so every run is trivially
autonomous. Reporting `1.0` would put a perfect score on an axis nobody measured
— the same mistake the leaderboard's cost and security columns exist to avoid.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from tooltrace.core.models import TraceEvent

#: Tools that observe the workspace without changing it. Used to tell "inspected
#: then acted" from "acted blind" -- the latter is not wrong, but it is worth a
#: reader's attention on a task whose answer depends on the input.
READ_TOOLS = frozenset(
    {"read_file", "list_directory", "search_text", "list_files", "search_files", "grep", "git"}
)

#: Tools that change the workspace.
WRITE_TOOLS = frozenset({"write_file", "patch_file", "delete_file", "apply_patch"})

#: Writes that carry the whole new content. These are the ones where "produced
#: output without observing input" is a meaningful observation.
BLIND_WRITE_TOOLS = frozenset({"write_file"})

#: A patch names the text it replaces and fails when that text is absent, so a
#: successful patch is itself evidence the agent knew what was there. Flagging a
#: patch-only run as "wrote without reading" would be wrong, and wrong in the
#: direction that matters: an accusation against an agent that did observe.
CONDITIONAL_WRITE_TOOLS = frozenset({"patch_file", "apply_patch"})

IMMEDIATE = "immediate"
DELAYED = "delayed"
ABANDONED = "abandoned"
SILENTLY_WRONG = "silently_wrong"


def _paired_calls(events: Sequence[TraceEvent]) -> list[dict[str, Any]]:
    """Each `tool_request` joined to the `tool_result` that follows it."""
    calls: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    for event in events:
        payload = dict(event.payload or {})
        if event.type == "tool_request":
            pending = {
                "seq": event.seq,
                "tool": str(payload.get("tool") or ""),
                "args": payload.get("args") or {},
                "status": None,
                "error": None,
                "result_summary": "",
            }
        elif event.type == "tool_result" and pending is not None:
            pending["status"] = payload.get("status")
            pending["error"] = payload.get("error")
            pending["result_summary"] = str(payload.get("result_summary") or "")
            pending["injected"] = bool((payload.get("data") or {}).get("injected"))
            pending["result_seq"] = event.seq
            calls.append(pending)
            pending = None
    if pending is not None:
        # A request with no result is a real state -- the run was cut off -- and
        # dropping it would hide the step the run died on.
        pending["status"] = "no_result"
        calls.append(pending)
    return calls


# --- recovery quality (F037) ------------------------------------------------


def recovery_quality(events: Sequence[TraceEvent], *, succeeded: bool) -> dict[str, Any]:
    """Grade each recovery from an injected fault.

    `recovered: true` currently covers three materially different behaviours:
    fixing it on the next call, fixing it after wandering, and getting the tool
    to succeed while still producing the wrong answer. The third is the worst
    outcome of the three and the score cannot distinguish it from the first.
    """
    calls = _paired_calls(events)
    faults = [c for c in calls if c.get("injected")]
    if not faults:
        return {"measurable": False, "reason": "no fault was injected in this run", "grades": []}

    grades: list[dict[str, Any]] = []
    for fault in faults:
        after = [c for c in calls if c["seq"] > fault["seq"]]
        same_tool_after = [c for c in after if c["tool"] == fault["tool"]]
        recovered_at = next((c for c in same_tool_after if c["status"] == "ok"), None)

        if recovered_at is None:
            grade, detail = ABANDONED, f"{fault['tool']} never succeeded after the fault"
            steps = None
        else:
            steps = sum(1 for c in after if c["seq"] < recovered_at["seq"])
            if steps == 0:
                grade = IMMEDIATE
                detail = f"retried {fault['tool']} on the very next call"
            else:
                grade = DELAYED
                detail = f"{steps} intervening call(s) before {fault['tool']} succeeded"
            if not succeeded:
                # The grade that matters. The tool recovered and the run is still
                # wrong, so "recovered" on its own is a misleading thing to read.
                grade = SILENTLY_WRONG
                detail += ", but the run did not meet its assertions"

        grades.append(
            {
                "tool": fault["tool"],
                "fault_at_seq": fault["seq"],
                "grade": grade,
                "steps_to_recover": steps,
                "detail": detail,
            }
        )

    worst_order = [ABANDONED, SILENTLY_WRONG, DELAYED, IMMEDIATE]
    worst = min((g["grade"] for g in grades), key=worst_order.index)
    return {
        "measurable": True,
        "faults": len(faults),
        "grades": grades,
        # The worst grade, not the average: an agent that recovered from three
        # faults and abandoned a fourth has a problem, and a mean would bury it.
        "worst_grade": worst,
    }


# --- error propagation (F033) -----------------------------------------------


def error_propagation(events: Sequence[TraceEvent]) -> dict[str, Any]:
    """Consecutive failures, and how far one error carried.

    A run with six failed calls could be six independent problems or one problem
    the agent kept hitting. Those need different responses, and a count cannot
    tell them apart.
    """
    calls = _paired_calls(events)
    failures = [c for c in calls if c["status"] not in (None, "ok")]
    if not failures:
        return {"chains": [], "longest_chain": 0, "failed_calls": 0, "independent_failures": 0}

    chains: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous_index: int | None = None
    for call in calls:
        index = calls.index(call)
        if call["status"] not in (None, "ok"):
            if previous_index is not None and index == previous_index + 1:
                current.append(call)
            else:
                if current:
                    chains.append(current)
                current = [call]
            previous_index = index

    if current:
        chains.append(current)

    described = [
        {
            "length": len(chain),
            "tools": [c["tool"] for c in chain],
            "from_seq": chain[0]["seq"],
            "to_seq": chain[-1]["seq"],
            # A chain of the same tool repeatedly is one problem hit repeatedly;
            # a chain of different tools is closer to a cascade.
            "same_tool": len({c["tool"] for c in chain}) == 1,
        }
        for chain in chains
    ]
    return {
        "failed_calls": len(failures),
        "chains": described,
        "longest_chain": max((c["length"] for c in described), default=0),
        "independent_failures": sum(1 for c in described if c["length"] == 1),
    }


# --- shortcut signals (F035) ------------------------------------------------


def shortcut_signals(
    events: Sequence[TraceEvent], task: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Observations that a passing run may not have done the work.

    Every entry is a **signal**, phrased as what was observed. This module has no
    standing to call an agent dishonest: a task may be legitimately solvable
    without reading anything, and a short solution may simply be a good one. What
    it can do is surface the runs a human should look at, which is what the
    research gap actually asks for -- "no way to distinguish genuine capability
    from benchmark gaming" is a request for evidence, not for a verdict.
    """
    calls = _paired_calls(events)
    reads = [c for c in calls if c["tool"] in READ_TOOLS and c["status"] == "ok"]
    writes = [c for c in calls if c["tool"] in WRITE_TOOLS and c["status"] == "ok"]
    blind_writes = [c for c in writes if c["tool"] in BLIND_WRITE_TOOLS]

    # A task with an empty starting workspace has nothing to read, so writing
    # without reading is the *correct* solution, not a shortcut. Without this,
    # "create a file containing hello" is flagged forever.
    had_input = bool((task or {}).get("starting_workspace"))

    signals: list[dict[str, str]] = []

    if blind_writes and not reads and had_input:
        signals.append(
            {
                "signal": "wrote_without_reading",
                "observed": (
                    f"{len(blind_writes)} whole-file write(s), no successful read, and "
                    f"{len((task or {}).get('starting_workspace') or {})} file(s) available to read"
                ),
                "check": (
                    "whether the task's answer depends on the input. If it does, the "
                    "agent produced it without looking at it"
                ),
            }
        )

    if writes and reads and all(w["seq"] < min(r["seq"] for r in reads) for w in writes):
        signals.append(
            {
                "signal": "wrote_before_reading",
                "observed": "every write happened before any read",
                "check": "whether the written content could have been known in advance",
            }
        )

    deletes = [c for c in calls if c["tool"] == "delete_file" and c["status"] == "ok"]
    if deletes:
        signals.append(
            {
                "signal": "deleted_files",
                "observed": f"{len(deletes)} file(s) deleted",
                "check": (
                    "whether deletion satisfies an assertion that a fix would also "
                    "satisfy -- emptying a failing test file passes 'no failures'"
                ),
            }
        )

    # An expected value appearing verbatim in a write argument is the strongest
    # available signal, and still only a signal: the correct answer legitimately
    # appears in the correct output.
    if task:
        expected = _expected_literals(task)
        for write in blind_writes:
            args_text = " ".join(str(v) for v in (write["args"] or {}).values())
            matched = sorted(e for e in expected if e and e in args_text)
            if matched and not reads:
                signals.append(
                    {
                        "signal": "wrote_expected_value_without_reading",
                        "observed": (
                            f"{write['tool']} at seq {write['seq']} wrote a value the task "
                            f"asserts on ({matched[:2]}), with no prior read"
                        ),
                        "check": "whether that value could have been derived rather than recalled",
                    }
                )
                break

    return {
        "signals": signals,
        "count": len(signals),
        # Deliberately not a boolean "cheated". A reviewer decides.
        "warrants_review": bool(signals),
        "statement": (
            "These are observations about a trace, not findings about an agent. A task may "
            "be solvable without reading anything, and a short solution may just be a good one."
        ),
    }


def _expected_literals(task: dict[str, Any]) -> list[str]:
    """Literal values the task's assertions expect, for the signal above."""
    literals: list[str] = []
    for assertion in task.get("assertions") or []:
        if str(assertion.get("type", "")).endswith("not_contains"):
            continue
        params = assertion.get("params") or {}
        for key in ("text", "expected", "contains", "value", "equals", "expected_csv"):
            value = params.get(key)
            if isinstance(value, str) and len(value) >= 4:
                literals.append(value)
        any_of = params.get("any_of")
        if isinstance(any_of, list):
            literals.extend(str(v) for v in any_of if isinstance(v, str) and len(str(v)) >= 4)
    return literals


# --- autonomy (F034) --------------------------------------------------------


def autonomy(events: Sequence[TraceEvent], task: dict[str, Any] | None = None) -> dict[str, Any]:
    """How much intervention the run needed.

    Counted from the **trace**, not from the task file. An intervention declared
    at a step the run never reached did not happen, and a metric that counted it
    would be restating the task rather than measuring the run.

    A task that declares no intervention is still reported as unmeasurable
    rather than scoring 1.0. Nobody interrupted the run, so it was trivially
    autonomous, and a perfect mark on an axis nobody measured is the failure the
    leaderboard's cost and security columns exist to avoid.

    Interventions are declared in `metadata` because the v1 task protocol is
    versioned and `tooltrace/tasks/v2.py` is marked do-not-touch; a top-level
    field is still honoured, so a v2 task that migrates forward keeps working.
    """
    metadata = (task or {}).get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    declared = list((task or {}).get("user_actions") or metadata.get("user_actions") or [])
    checkpoints = list((task or {}).get("checkpoints") or metadata.get("checkpoints") or [])

    performed = [e for e in events if e.type in ("user_action", "checkpoint")]
    denials = [
        e for e in events if e.type == "checkpoint" and (e.payload or {}).get("state") == "denied"
    ]

    if not declared and not checkpoints and not performed:
        return {
            "measurable": False,
            "reason": (
                "this task declares no interventions or checkpoints, so the run was "
                "trivially autonomous and the number would mean nothing"
            ),
            "score": None,
            "interventions": 0,
        }

    steps = sum(1 for e in events if e.type == "tool_request")
    interventions = len(performed)
    return {
        "measurable": True,
        "score": round(max(0.0, 1.0 - interventions / max(steps, 1)), 6),
        "interventions": interventions,
        "declared": len(declared) + len(checkpoints),
        "steps": steps,
        # A denial is the sharpest form of intervention: the run did not merely
        # receive guidance, it was refused. Counted separately because a run
        # stopped by a gate is not a run that needed less help.
        "denied": len(denials),
        "note": (
            "Counted from the trace, so an intervention declared at a step the run "
            "never reached is not counted. An agent that needed help it was never "
            "offered is still not distinguishable from one that did not need it."
        ),
    }


# --- the whole picture ------------------------------------------------------


def behaviour_report(
    events: Sequence[TraceEvent], *, succeeded: bool, task: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Everything above, for one run."""
    return {
        "recovery": recovery_quality(events, succeeded=succeeded),
        "errors": error_propagation(events),
        "shortcuts": shortcut_signals(events, task),
        "autonomy": autonomy(events, task),
    }


def aggregate_behaviour(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-run behaviour reports into one block."""
    if not reports:
        return {}

    grades: dict[str, int] = {}
    for report in reports:
        recovery = report.get("recovery") or {}
        for grade in recovery.get("grades") or []:
            grades[str(grade["grade"])] = grades.get(str(grade["grade"]), 0) + 1

    flagged = [r for r in reports if (r.get("shortcuts") or {}).get("warrants_review")]
    signal_counts: dict[str, int] = {}
    for report in flagged:
        for signal in (report.get("shortcuts") or {}).get("signals") or []:
            name = str(signal["signal"])
            signal_counts[name] = signal_counts.get(name, 0) + 1

    chains = [int((r.get("errors") or {}).get("longest_chain") or 0) for r in reports]
    autonomy_scores: list[float] = []
    for report in reports:
        score = (report.get("autonomy") or {}).get("score")
        if isinstance(score, int | float):
            autonomy_scores.append(float(score))

    return {
        "runs": len(reports),
        "recovery_grades": grades,
        # Named separately because it is the one that a passing score hides.
        "silently_wrong_recoveries": grades.get(SILENTLY_WRONG, 0),
        "runs_warranting_review": len(flagged),
        "shortcut_signals": signal_counts,
        "longest_error_chain": max(chains, default=0),
        "autonomy_mean": (
            round(sum(autonomy_scores) / len(autonomy_scores), 6) if autonomy_scores else None
        ),
    }
