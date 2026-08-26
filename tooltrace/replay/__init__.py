"""Deterministic replay of non-model tool interactions from a trace.

Replaying a trace re-executes every recorded ``tool_request`` against a fresh
sandbox workspace and compares the resulting ``tool_result`` summaries. Model
messages are skipped by design: only the deterministic tool layer is replayed,
so results are reproducible regardless of model nondeterminism.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from tooltrace.core.models import TaskDefinition, TraceEvent
from tooltrace.tools.base import ToolContext
from tooltrace.tools.executor import ToolExecutor


@dataclass
class ReplayReport:
    total_requests: int = 0
    matched: int = 0
    mismatched: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatched and not self.errors


def replay_trace(
    task: TaskDefinition, events: list[TraceEvent], *, compare_status_only: bool = True
) -> ReplayReport:
    """Replay all tool_request/tool_result pairs from *events*."""
    report = ReplayReport()

    pending_tool: str | None = None
    pending_args: dict = {}
    request_seq: int | None = None

    # Pair each tool_request with its following tool_result.
    pairs: list[tuple[int, str, dict, TraceEvent]] = []
    for e in events:
        if e.type == "tool_request":
            pending_tool = str(e.payload.get("tool"))
            request_seq = e.seq
            args = e.payload.get("args")
            pending_args = dict(args) if isinstance(args, dict) else {}
        elif e.type == "tool_result" and pending_tool is not None:
            if request_seq is not None:
                pairs.append((request_seq, pending_tool, pending_args, e))
            pending_tool = None
            request_seq = None

    if not pairs:
        return report

    engine = None
    from tooltrace.perturbations import PerturbationEngine

    engine = PerturbationEngine(task.perturbations)

    with tempfile.TemporaryDirectory(prefix="tooltrace-replay-") as tmp:
        sandbox_root = Path(tmp)
        workspace = sandbox_root / "workspace"
        workspace.mkdir()
        for rel, content in task.starting_workspace.items():
            p = workspace / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        engine.prepare_workspace(workspace)

        ctx = ToolContext(workspace=workspace, network_policy=task.network_policy.value)
        executor = ToolExecutor(ctx, task.allowed_tools, emit_event=lambda ev: None)

        for seq, tool, _args, expected_result in pairs:
            report.total_requests += 1
            try:
                result = executor.execute(tool, _args)
            except Exception as exc:
                report.errors.append(f"seq {seq}: replay raised {exc}")
                continue
            actual_status = "ok" if result.ok else "error"
            expected_status = str(expected_result.payload.get("status"))
            if compare_status_only:
                if actual_status == expected_status or (
                    expected_status == "denied" and actual_status == "error"
                ):
                    report.matched += 1
                else:
                    report.mismatched.append(
                        f"seq {seq}: {tool} expected {expected_status}, got {actual_status}"
                    )
    return report


def replay_from_checkpoint(
    task: TaskDefinition,
    events: list[TraceEvent],
    checkpoint_seq: int,
    *,
    compare_status_only: bool = True,
) -> ReplayReport:
    """Partial replay (feature 80): re-execute only tool interactions at or
    after *checkpoint_seq*, skipping the verified prefix. Useful for debugging
    long trajectories without re-running expensive early steps. The skipped
    prefix is reported as an informational note so callers never mistake a
    partial replay for a full one.
    """
    prefix = [e for e in events if e.seq is not None and e.seq < checkpoint_seq]
    suffix = [e for e in events if e.seq is None or e.seq >= checkpoint_seq]
    report = replay_trace(task, suffix, compare_status_only=compare_status_only)
    skipped_tools = sum(1 for e in prefix if e.type == "tool_request")
    report.errors.insert(
        0,
        f"partial-replay: skipped {len(prefix)} events "
        f"({skipped_tools} tool requests) before checkpoint seq={checkpoint_seq}",
    )
    return report
