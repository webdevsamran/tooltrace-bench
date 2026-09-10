"""Scripted mid-run interventions: a user who changes their mind, and a checkpoint.

`UserAction` and `CheckpointStage` have existed in `tooltrace/tasks/v2.py` since
the protocol was written, and nothing has ever performed one. That is why
`analysis/behaviour.py` reports autonomy as `measurable: false`: every run
completes with zero interventions, so an autonomy score of 1.0 would be a perfect
mark on an axis nobody measured.

This is the executor. It performs two kinds of thing at a declared step:

- **A user action** mutates the world mid-run — writes a file, deletes one, or
  delivers a message. That is how you build a task where the user changes their
  mind halfway through, which is the most common real failure mode nobody
  benchmarks: an agent that has already committed to a plan and cannot revise it.
- **A checkpoint** requires approval before the run continues. Dual control:
  the agent proposes, a policy decides, and a run that proceeds without approval
  is a run that ignored its own gate.

Three constraints, and they exist because an intervention engine is an easy place
to make a benchmark dishonest:

1. **Every intervention is recorded in the trace.** A world that changed without
   a trace entry would make a run unreproducible and unexplainable, which is the
   opposite of what this project sells.
2. **Interventions are declarative and ordered by step**, never conditional on
   what the agent did. A condition on agent behaviour is an adversary, not a
   user, and an adversary that reacts is not reproducible.
3. **An enforced denial stops the run.** A system gate that logs and continues
   is not a gate, which is the rule `BudgetGuard` follows and for the same
   reason. An *advisory* denial is delivered and the agent may proceed -- and
   those measure different things. Enforced tests the harness, and whether the
   agent acted before approval arrived. Advisory tests the agent: does it
   respect a refusal it could ignore? A benchmark needs both, and letting one
   stand in for the other would make a compliant harness look like a compliant
   agent.

They are read from `task.metadata`, not from a new field on `TaskDefinition`. The
v1 task protocol is versioned and `tooltrace/tasks/v2.py` is marked do-not-touch;
`metadata` is free-form by design, so a task can declare interventions today
without a protocol migration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WRITE = "write_file"
DELETE = "delete_file"
APPEND = "append_file"
MESSAGE = "message"

#: What a user action may do. Deliberately small: an intervention that could run
#: arbitrary code would be a second agent, and the run would no longer be a
#: measurement of the first one.
KINDS = frozenset({WRITE, DELETE, APPEND, MESSAGE})

APPROVED = "approved"
DENIED = "denied"
PENDING = "pending"


@dataclass(frozen=True)
class UserAction:
    """One scripted thing the simulated user does, at a given step."""

    at_step: int
    kind: str
    path: str = ""
    content: str = ""
    message: str = ""

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> UserAction | None:
        kind = str(raw.get("kind") or "")
        if kind not in KINDS:
            return None
        try:
            at_step = int(raw.get("at_step", 0))
        except (TypeError, ValueError):
            return None
        return cls(
            at_step=max(0, at_step),
            kind=kind,
            path=str(raw.get("path") or ""),
            content=str(raw.get("content") or ""),
            message=str(raw.get("message") or ""),
        )


@dataclass(frozen=True)
class Checkpoint:
    """A gate the run must pass at a given step."""

    at_step: int
    stage: str
    #: `approve` is the task's declaration of what the policy decides. A task
    #: that gates and always approves tests nothing, so a denial is expressible.
    approve: bool = True
    reason: str = ""
    #: Whether a denial *stops* the run, and it changes what is being measured.
    #:
    #: `True` (default) is a system gate: the harness enforces dual control, and
    #: the task tests the harness plus whether the agent acted *before* its
    #: approval arrived. An agent cannot fail it by ignoring the denial, because
    #: it never gets the chance.
    #:
    #: `False` is advisory: the denial is delivered as an observation and the
    #: agent may proceed anyway. That tests the agent -- does it respect a
    #: refusal it could ignore -- which is a different and equally real question.
    #: A benchmark needs both, and conflating them would let one stand in for
    #: the other.
    enforced: bool = True

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Checkpoint | None:
        try:
            at_step = int(raw.get("at_step", 0))
        except (TypeError, ValueError):
            return None
        stage = str(raw.get("stage") or "review")
        return cls(
            at_step=max(0, at_step),
            stage=stage,
            approve=bool(raw.get("approve", True)),
            reason=str(raw.get("reason") or ""),
            enforced=bool(raw.get("enforced", True)),
        )


def parse_interventions(metadata: dict[str, Any]) -> tuple[list[UserAction], list[Checkpoint]]:
    """Read a task's declared interventions out of its metadata."""
    raw_actions = metadata.get("user_actions")
    raw_checkpoints = metadata.get("checkpoints")
    actions = [
        action
        for item in (raw_actions if isinstance(raw_actions, list) else [])
        if isinstance(item, dict) and (action := UserAction.parse(item)) is not None
    ]
    checkpoints = [
        checkpoint
        for item in (raw_checkpoints if isinstance(raw_checkpoints, list) else [])
        if isinstance(item, dict) and (checkpoint := Checkpoint.parse(item)) is not None
    ]
    return sorted(actions, key=lambda a: a.at_step), sorted(checkpoints, key=lambda c: c.at_step)


@dataclass
class InterventionEngine:
    """Applies a task's declared interventions as a run proceeds."""

    actions: list[UserAction] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    applied: list[dict[str, Any]] = field(default_factory=list)
    denied_at: int | None = None
    _fired_actions: set[int] = field(default_factory=set)
    _fired_checkpoints: set[int] = field(default_factory=set)

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> InterventionEngine:
        actions, checkpoints = parse_interventions(metadata or {})
        return cls(actions=actions, checkpoints=checkpoints)

    @property
    def active(self) -> bool:
        return bool(self.actions or self.checkpoints)

    @property
    def intervention_count(self) -> int:
        return len(self.actions) + len(self.checkpoints)

    def apply_at(
        self,
        step: int,
        workspace: Path,
        emit: Callable[[str, dict[str, Any]], None],
    ) -> list[str]:
        """Perform everything scheduled for this step; return new observations.

        Messages come back as observations so the agent actually sees them --
        a simulated user whose message the agent never receives is a file write
        with extra steps.
        """
        observations: list[str] = []

        for index, action in enumerate(self.actions):
            if action.at_step != step or index in self._fired_actions:
                continue
            self._fired_actions.add(index)
            detail = self._perform(action, workspace)
            # Recorded before it takes effect on the agent's view, so a reader
            # of the trace sees the cause before the consequence.
            emit(
                "user_action",
                {
                    "kind": action.kind,
                    "at_step": step,
                    "path": action.path,
                    "detail": detail,
                },
            )
            self.applied.append({"kind": action.kind, "at_step": step, "detail": detail})
            if action.kind == MESSAGE:
                observations.append(f"[user] {action.message}")

        for index, checkpoint in enumerate(self.checkpoints):
            if checkpoint.at_step != step or index in self._fired_checkpoints:
                continue
            self._fired_checkpoints.add(index)
            state = APPROVED if checkpoint.approve else DENIED
            emit(
                "checkpoint",
                {
                    "stage": checkpoint.stage,
                    "at_step": step,
                    "state": state,
                    "reason": checkpoint.reason,
                    "enforced": checkpoint.enforced,
                },
            )
            self.applied.append(
                {"kind": "checkpoint", "at_step": step, "detail": f"{checkpoint.stage}: {state}"}
            )
            if not checkpoint.approve:
                observations.append(
                    f"[checkpoint] {checkpoint.stage} denied: "
                    f"{checkpoint.reason or 'no reason given'}"
                    + ("" if checkpoint.enforced else ". You may still act; the decision is yours.")
                )
                if checkpoint.enforced:
                    # A system gate that logs and continues is not a gate.
                    self.denied_at = step

        return observations

    def _perform(self, action: UserAction, workspace: Path) -> str:
        """Mutate the workspace. Never escapes it."""
        if action.kind == MESSAGE:
            return action.message[:200]

        # Same containment rule as the tool layer: a user action that could
        # write outside the workspace would be a sandbox escape wearing a
        # task's clothes.
        target = (workspace / action.path).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError:
            return f"refused: {action.path} is outside the workspace"

        if action.kind == DELETE:
            if target.is_file():
                target.unlink()
                return f"deleted {action.path}"
            return f"{action.path} was already absent"

        target.parent.mkdir(parents=True, exist_ok=True)
        if action.kind == APPEND:
            existing = target.read_text(encoding="utf-8") if target.is_file() else ""
            target.write_text(existing + action.content, encoding="utf-8")
            return f"appended {len(action.content)} chars to {action.path}"

        target.write_text(action.content, encoding="utf-8")
        return f"wrote {len(action.content)} chars to {action.path}"

    def summary(self) -> dict[str, Any]:
        return {
            "declared": self.intervention_count,
            "applied": len(self.applied),
            "actions": self.applied,
            "denied_at_step": self.denied_at,
            "stopped_by_checkpoint": self.denied_at is not None,
        }
