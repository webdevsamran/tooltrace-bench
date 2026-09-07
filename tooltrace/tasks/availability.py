"""Whether a task can run on this machine at all.

A task that needs a toolchain the machine does not have must be *skipped*,
never scored. A missing `cargo` says nothing about how an agent behaves, and
recording it as a failure would make benchmark results depend on the runner's
installed software rather than on the agent -- exactly the kind of
environment-dependent comparison this project refuses to make elsewhere.
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

    @property
    def reason(self) -> str:
        if self.runnable:
            return ""
        joined = ", ".join(self.missing)
        return f"required tool(s) not on PATH: {joined}"


def missing_tools(task: TaskDefinition) -> tuple[str, ...]:
    """Which of a task's `requires_tools` are absent from PATH."""
    return tuple(t for t in task.requires_tools if shutil.which(t) is None)


def availability(task: TaskDefinition) -> Availability:
    absent = missing_tools(task)
    return Availability(runnable=not absent, missing=absent)


def partition(
    tasks: list[TaskDefinition],
) -> tuple[list[TaskDefinition], list[tuple[TaskDefinition, str]]]:
    """Split tasks into (runnable, [(skipped, reason)])."""
    runnable: list[TaskDefinition] = []
    skipped: list[tuple[TaskDefinition, str]] = []
    for task in tasks:
        state = availability(task)
        if state.runnable:
            runnable.append(task)
        else:
            skipped.append((task, state.reason))
    return runnable, skipped
