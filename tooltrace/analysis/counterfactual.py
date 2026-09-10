"""Would it still pass with one tool taken away?

Two agents can score identically and be doing entirely different things. One has
a plan and adapts when a tool is missing; the other is walking a path it has
walked before and falls over at the first change. Nothing else in this project
distinguishes them, because every other metric reads a run in which everything
worked.

An ablation makes the difference visible: run the task once per tool with that
tool removed from `allowed_tools`, and see what survives. A tool whose removal
breaks the task was **load-bearing**. One whose removal changes nothing was
**redundant on this run**, which is not the same as useless. And a tool the
agent never called at all is **unused**, which is the finding that most often
means the task's declared tools are wrong rather than the agent's behaviour.

## Two things this is not, stated because both are easy to assume

**An ablation is not a clean intervention.** Removing a tool also removes its
line from the catalogue the model reads, so the agent is being told something
different rather than merely given less. The change in outcome is the sum of
both, and no amount of arithmetic here separates them.

**One run per arm is one Bernoulli draw.** With a nondeterministic agent, "it
failed without `search_text`" may be a coin landing differently. The report
counts runs per arm and flags a small sample rather than presenting a
single-run verdict as a property of the agent.
"""

from __future__ import annotations

from typing import Any, Protocol

LOAD_BEARING = "load_bearing"
REDUNDANT = "redundant"
UNUSED = "unused"
BASELINE_FAILED = "baseline_failed"


class Runner(Protocol):
    """The part of `TaskRunner` this needs, so a test can pass a fake."""

    def run(
        self,
        task: Any,
        agent_name: str,
        agent_config: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> tuple[Any, list[Any], str]: ...


def _copy_without(task: Any, tool: str) -> Any:
    """The task with one tool removed from `allowed_tools`.

    A copy, because mutating the loaded task would leak the ablation into every
    later run in the same process -- including the baseline of the next task.
    """
    clone = task.model_copy(deep=True)
    clone.allowed_tools = [t for t in task.allowed_tools if t != tool]
    return clone


def _tools_called(events: list[Any]) -> set[str]:
    called: set[str] = set()
    for event in events:
        kind = getattr(event, "type", None) or (
            event.get("type") if isinstance(event, dict) else ""
        )
        if kind != "tool_request":
            continue
        payload = getattr(event, "payload", None)
        if payload is None and isinstance(event, dict):
            payload = event.get("payload")
        name = (payload or {}).get("tool")
        if isinstance(name, str) and name:
            called.add(name)
    return called


def ablate(
    task: Any,
    agent_name: str,
    agent_config: dict[str, object] | None,
    runner: Runner,
    *,
    runs_per_arm: int = 1,
) -> dict[str, Any]:
    """Run the baseline, then one arm per allowed tool with that tool removed."""
    baseline_results = [
        runner.run(task, agent_name, agent_config, run_id=f"cf-baseline-{i}")
        for i in range(runs_per_arm)
    ]
    baseline_passes = sum(1 for result, _events, _diff in baseline_results if result.success)
    called = set()
    for _result, events, _diff in baseline_results:
        called |= _tools_called(events)

    if baseline_passes == 0:
        # Ablating a task the agent cannot do anyway measures nothing: every arm
        # fails, and every tool would read as load-bearing.
        return {
            "task_id": getattr(task, "id", ""),
            "agent": agent_name,
            "runs_per_arm": runs_per_arm,
            "baseline_passes": 0,
            "measurable": False,
            "reason": (
                "the agent did not pass the task with every tool available, so removing one "
                "measures nothing: every arm fails and every tool reads as load-bearing"
            ),
            "arms": [],
        }

    arms: list[dict[str, Any]] = []
    for tool in sorted(task.allowed_tools):
        if tool not in called:
            arms.append(
                {
                    "tool": tool,
                    "verdict": UNUSED,
                    "passes": None,
                    "runs": 0,
                    "note": _unused_note(task),
                }
            )
            continue

        reduced = _copy_without(task, tool)
        passes = 0
        for index in range(runs_per_arm):
            result, _events, _diff = runner.run(
                reduced, agent_name, agent_config, run_id=f"cf-{tool}-{index}"
            )
            if result.success:
                passes += 1
        arms.append(
            {
                "tool": tool,
                "verdict": LOAD_BEARING if passes == 0 else REDUNDANT,
                "passes": passes,
                "runs": runs_per_arm,
                "note": (
                    "removing it made the task fail on every attempt"
                    if passes == 0
                    else (
                        f"the task still passed {passes}/{runs_per_arm} time(s) without it. "
                        "Redundant on this run is not the same as useless: the agent found "
                        "another way, which may be a worse one"
                    )
                ),
            }
        )

    load_bearing = [a["tool"] for a in arms if a["verdict"] == LOAD_BEARING]
    unused = [a["tool"] for a in arms if a["verdict"] == UNUSED]
    return {
        "task_id": getattr(task, "id", ""),
        "agent": agent_name,
        "runs_per_arm": runs_per_arm,
        "baseline_passes": baseline_passes,
        "measurable": True,
        "arms": arms,
        "load_bearing": load_bearing,
        "unused": unused,
        "sample_is_small": runs_per_arm < 5,
        "statement": _statement(arms, load_bearing, unused, runs_per_arm),
        "caveat": (
            "Removing a tool also removes its line from the catalogue the model reads, so "
            "the agent is told something different rather than merely given less. The change "
            "in outcome is the sum of both and nothing here separates them."
        ),
    }


def _unused_note(task: Any) -> str:
    """Why a declared tool went uncalled -- and it is not always a mistake.

    On an ordinary task an uncalled tool usually means the task declares more
    than it needs. On a *security* task it often means the opposite: the tool
    is there because the **attack** needs it, and a resistant agent never
    touching it is the pass condition. Removing it would make the attack
    unreachable and every agent would look perfectly safe -- which is a bug this
    repository has actually shipped.
    """
    if str(getattr(task, "id", "")).startswith("security/"):
        return (
            "never called with everything available. On a security task that is often "
            "correct: the tool is declared because the attack needs it, and a resistant "
            "agent not touching it is the pass condition"
        )
    return (
        "never called even with everything available, so nothing was removed. This "
        "usually means the task declares a tool it does not need"
    )


def _statement(
    arms: list[dict[str, Any]], load_bearing: list[str], unused: list[str], runs: int
) -> str:
    tried = [a for a in arms if a["verdict"] != UNUSED]
    parts = [
        f"{len(load_bearing)} of {len(tried)} tool(s) the agent used were load-bearing"
        + (f": {', '.join(load_bearing)}" if load_bearing else "")
    ]
    if unused:
        parts.append(
            f"{len(unused)} declared tool(s) were never called ({', '.join(unused)}) -- see "
            "each row for whether that is a surplus declaration or the attack surface"
        )
    if runs < 5:
        parts.append(
            f"{runs} run(s) per arm: with a nondeterministic agent this is a draw rather "
            "than a property"
        )
    return "; ".join(parts) + "."


def render_markdown(report: dict[str, Any]) -> str:
    if not report.get("measurable"):
        return f"### Counterfactual\n\nNot measurable: {report['reason']}\n"
    lines = [
        "### Counterfactual: which tools were load-bearing",
        "",
        "| Removed | Verdict | Passed | Note |",
        "|---|---|---|---|",
    ]
    for arm in report["arms"]:
        passed = "n/a" if arm["passes"] is None else f"{arm['passes']}/{arm['runs']}"
        lines.append(f"| `{arm['tool']}` | {arm['verdict']} | {passed} | {arm['note']} |")
    lines += ["", report["statement"], "", f"*{report['caveat']}*", ""]
    return "\n".join(lines)
