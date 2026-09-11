"""Whether a task can run on this machine, against this agent, at all.

A task that needs a toolchain the machine does not have must be *skipped*,
never scored. A missing `cargo` says nothing about how an agent behaves, and
recording it as a failure would make benchmark results depend on the runner's
installed software rather than on the agent -- exactly the kind of
environment-dependent comparison this project refuses to make elsewhere.

The same rule now covers attachments, for the same reason. A task carrying a
screenshot, run against an adapter with nowhere to put an image, is not a task
the agent failed: the agent was never shown the question. A text-only model
asked about a screenshot answers fluently and wrongly, so the failure would look
exactly like a real one -- which is why it is refused here rather than scored
and caveated later.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

from tooltrace.core.models import TaskDefinition


@dataclass(frozen=True)
class Availability:
    """Whether a task is runnable here, and why not if it is not."""

    runnable: bool
    missing: tuple[str, ...] = ()
    #: Set when the blocker is the *agent* rather than the machine.
    blocked_by_agent: str = ""

    @property
    def reason(self) -> str:
        if self.runnable:
            return ""
        if self.blocked_by_agent:
            return self.blocked_by_agent
        joined = ", ".join(self.missing)
        return f"required tool(s) not on PATH: {joined}"


def missing_tools(task: TaskDefinition) -> tuple[str, ...]:
    """Which of a task's `requires_tools` are absent from PATH."""
    return tuple(t for t in task.requires_tools if shutil.which(t) is None)


def vision_gap(task: TaskDefinition, agent: str | None) -> str:
    """Why this agent cannot be shown this task's attachments, or "".

    An unnamed agent is not a blocked one: `tooltrace tasks` lists what exists
    without knowing what will run it, and reporting every attachment task as
    unrunnable there would be answering a question nobody asked.
    """
    if not task.attachments or not agent:
        return ""
    from tooltrace.agents.vision import support_for

    support = support_for(agent)
    if support.can_reach_the_image:
        return ""
    return (
        f"{len(task.attachments)} attachment(s) and the `{agent}` adapter has nowhere "
        f"to put an image: {support.note}"
    )


def availability(task: TaskDefinition, agent: str | None = None) -> Availability:
    absent = missing_tools(task)
    if absent:
        return Availability(runnable=False, missing=absent)
    gap = vision_gap(task, agent)
    if gap:
        return Availability(runnable=False, blocked_by_agent=gap)
    return Availability(runnable=True)


def partition(
    tasks: list[TaskDefinition], agent: str | None = None
) -> tuple[list[TaskDefinition], list[tuple[TaskDefinition, str]]]:
    """Split tasks into (runnable, [(skipped, reason)])."""
    runnable: list[TaskDefinition] = []
    skipped: list[tuple[TaskDefinition, str]] = []
    for task in tasks:
        state = availability(task, agent)
        if state.runnable:
            runnable.append(task)
        else:
            skipped.append((task, state.reason))
    return runnable, skipped
