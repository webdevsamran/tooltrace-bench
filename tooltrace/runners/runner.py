"""Single-task evaluation runner.

Owns the agent/tool loop described in ARCHITECTURE.md:
sandbox → snapshot → agent loop through the ToolExecutor → diff → scoring →
failure classification → EvalResult.
"""

from __future__ import annotations

import platform
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tooltrace.agents.base import AgentAdapter
from tooltrace.analysis.failures import classify
from tooltrace.core.models import (
    AgentContext,
    AgentOutcome,
    EvalResult,
    TaskDefinition,
    TraceEvent,
    TrustState,
    UsageMetadata,
)
from tooltrace.perturbations import PerturbationEngine
from tooltrace.sandbox.diff import changed_paths, snapshot, workspace_diff
from tooltrace.sandbox.local import TempWorkspaceSandbox
from tooltrace.scoring.composite import is_partial_success, is_success, score_task
from tooltrace.security.sanitize import sanitize_obj, summarize
from tooltrace.tools.base import ToolContext
from tooltrace.tools.executor import ToolExecutor

BACKSLASH = chr(92)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TaskRunner:
    """Runs one agent against one task exactly once."""

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir

    # -- public API ---------------------------------------------------------

    def run(
        self,
        task: TaskDefinition,
        agent_name: str,
        agent_config: dict[str, object] | None = None,
        run_id: str | None = None,
    ) -> tuple[EvalResult, list[TraceEvent], str]:
        """Execute the task. Returns (result, trace_events, workspace_diff_text)."""
        from tooltrace.core.registry import agent_registry

        run_id = run_id or uuid.uuid4().hex[:12]
        started_at = _now_iso()
        events: list[TraceEvent] = []
        seq = 0

        def emit(type_: str, payload: dict[str, object]) -> None:
            nonlocal seq
            seq += 1
            events.append(
                TraceEvent(
                    timestamp=_now_iso(),
                    seq=seq,
                    type=type_,  # type: ignore[arg-type]
                    payload=sanitize_obj(payload),  # type: ignore[arg-type]
                )
            )

        emit(
            "task_start",
            {
                "run_id": run_id,
                "task_id": task.id,
                "task_version": task.version,
                "agent": agent_name,
                "max_steps": task.max_steps,
                "timeout_seconds": task.timeout_seconds,
                "network_policy": task.network_policy.value,
            },
        )

        engine = PerturbationEngine(task.perturbations)
        sandbox = TempWorkspaceSandbox()
        timed_out = False
        outcome: AgentOutcome | None = None
        try:
            workspace = sandbox.start(task)
            engine.prepare_workspace(workspace)

            tool_ctx = ToolContext(
                workspace=workspace,
                network_policy=task.network_policy.value,
                http_allowlist=list(task.metadata.get("http_allowlist", [])),  # type: ignore[arg-type]
                env_allowlist=list(task.metadata.get("env_allowlist", [])),  # type: ignore[arg-type]
            )
            executor = ToolExecutor(
                ctx=tool_ctx,
                allowed_tools=task.allowed_tools,
                emit_event=lambda ev: events.append(ev),
                seq_start=seq,
                perturbation_hook=engine.hook if engine.active else None,
            )

            before = snapshot(workspace)
            adapter_cls = agent_registry.get(agent_name)
            adapter: AgentAdapter = (
                adapter_cls(agent_config) if isinstance(adapter_cls, type) else adapter_cls
            )
            ctx = AgentContext(
                task_id=task.id,
                objective=task.objective,
                description=task.description,
                workspace_files=sorted(before.keys()),
                allowed_tools=list(task.allowed_tools),
                max_steps=task.max_steps,
                timeout_seconds=task.timeout_seconds,
                extra={"workspace_path": str(workspace)},
            )
            adapter.initialize(ctx)

            observations: list[str] = []
            wall_start = time.perf_counter()
            deadline = wall_start + task.timeout_seconds
            step = 0
            while step < task.max_steps:
                if time.perf_counter() > deadline:
                    timed_out = True
                    break
                step += 1
                action = adapter.act(step, observations)
                if action.message:
                    emit("agent_message", {"message": summarize(action.message, 500)})
                if action.kind == "finish":
                    break
                if action.kind == "message":
                    continue
                if action.tool is None:
                    break
                result = executor.execute(action.tool, action.args)
                observations.append(
                    f"[{action.tool}] "
                    + (result.output[:1000] if result.ok else f"ERROR: {result.error}")
                )
                if not result.ok and engine.injected_count > 0:
                    emit(
                        "retry_recovery",
                        {
                            "tool": action.tool,
                            "phase": "failed",
                            "injected": bool(result.data.get("injected")),
                        },
                    )

            wall_ms = (time.perf_counter() - wall_start) * 1000.0
            outcome = adapter.finalize()

            # Pair failed→succeeded same-tool calls as recoveries.
            self._mark_recoveries(events)

            after = snapshot(workspace)
            diff_text = workspace_diff(before, after)
            changed = changed_paths(before, after)
            emit("workspace_diff", {"changed_paths": changed, "diff_bytes": len(diff_text)})

            score, details = score_task(task, workspace)
            success = is_success(score)
            partial = is_partial_success(score)
            emit(
                "validation",
                {
                    "score_total": score.total,
                    "components": score.components,
                    "details": details,
                    "success": success,
                },
            )

            classification = classify(
                events,
                finish_reason=outcome.finish_reason,
                timed_out=timed_out,
                score_total=score.total,
            )

            recovered: bool | None = (
                (engine.injected_count > 0 and success) if engine.injected_count else None
            )
            usage = outcome.usage or UsageMetadata()
            result_model = EvalResult(
                run_id=run_id,
                task_id=task.id,
                task_version=task.version,
                agent=agent_name,
                agent_config=dict(agent_config or {}),
                success=success,
                partial_success=partial,
                score=score,
                failure_reason=classification.reason,
                failure_detail=f"{classification.rule}: {classification.detail}".strip(": "),
                steps=step,
                tool_calls=executor.stats.tool_calls,
                failed_tool_calls=executor.stats.failed_tool_calls,
                invalid_tool_calls=executor.stats.invalid_tool_calls,
                repeated_calls=executor.stats.repeated_calls,
                unnecessary_changes=self._count_unnecessary(changed, task),
                workspace_violations=sum(
                    1
                    for e in events
                    if e.type == "tool_result" and e.payload.get("status") == "denied"
                ),
                test_pass_ratio=self._test_ratio(events),
                wall_ms=round(wall_ms, 3),
                model_ms=usage.model_time_ms,
                tool_ms=round(executor.stats.tool_ms, 3),
                usage=usage,
                trust_state=TrustState.LOCAL,
                started_at=started_at,
                finished_at=_now_iso(),
            )
            emit(
                "task_end",
                {
                    "success": success,
                    "failure_reason": classification.reason.value,
                    "recovered": recovered,
                    "injected_faults": engine.injected_count,
                },
            )
            return result_model, events, diff_text
        finally:
            sandbox.cleanup()

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _mark_recoveries(events: list[TraceEvent]) -> None:
        last_fail: dict[str, int] = {}
        for e in events:
            if e.type != "tool_result":
                continue
            tool = str(e.payload.get("tool"))
            if e.payload.get("status") == "error":
                last_fail[tool] = e.seq
            elif e.payload.get("status") == "ok" and tool in last_fail:
                for ev in events:
                    if (
                        ev.type == "retry_recovery"
                        and ev.payload.get("tool") == tool
                        and ev.payload.get("phase") == "failed"
                        and ev.seq == last_fail[tool]
                    ):
                        ev.payload["recovered"] = True

    @staticmethod
    def _count_unnecessary(changed: list[str], task: TaskDefinition) -> int:
        """Changed paths that neither existed initially nor appear in any
        assertion params are counted as unnecessary changes."""
        referenced: set[str] = set()
        for a in task.assertions:
            for v in a.params.values():
                if isinstance(v, str):
                    referenced.add(v.replace(BACKSLASH, "/").lstrip("./"))
        initial = set(task.starting_workspace.keys())
        return sum(
            1
            for p in changed
            if p not in initial
            and p not in referenced
            and not any(p.startswith(r.rstrip("/") + "/") for r in referenced)
        )

    @staticmethod
    def _test_ratio(events: list[TraceEvent]) -> float | None:
        ratios = [
            e.payload["data"]["pass_ratio"]
            for e in events
            if e.type == "tool_result"
            and isinstance(e.payload.get("data"), dict)
            and isinstance(e.payload["data"].get("pass_ratio"), float)
        ]
        return ratios[-1] if ratios else None


def environment_metadata() -> dict[str, object]:
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "os": platform.system(),
        "machine": platform.machine(),
        "timestamp": _now_iso(),
    }
