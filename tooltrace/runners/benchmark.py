"""Repeated-run benchmark runner (`tooltrace benchmark --runs N`).

Runs each task N times, writes a bundle per run, and aggregates reliability
statistics (success rate with Wilson CI, steps/tool calls, latency p50/p95,
recovery rate when perturbations are present).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from tooltrace.bundles import write_bundle
from tooltrace.core.models import BenchmarkRun, EvalResult
from tooltrace.core.versions import compatibility_key
from tooltrace.runners.runner import TaskRunner
from tooltrace.stats import summarize_reliability


def run_benchmark(
    tasks: list,
    agent_name: str,
    agent_config: dict[str, object] | None = None,
    runs: int = 1,
    out_dir: Path | None = None,
) -> BenchmarkRun:
    if runs < 1:
        raise ValueError("runs must be >= 1")
    runner = TaskRunner(output_dir=out_dir)
    run_id = uuid.uuid4().hex[:12]

    def _config_for(task) -> dict[str, object] | None:
        if agent_config is not None:
            return dict(agent_config)
        if agent_name == "scripted":
            script = task.metadata.get("scripted_script")
            if isinstance(script, list):
                return {"script": script}
        return None

    all_results: list[EvalResult] = []
    per_task_summary: dict[str, dict[str, object]] = {}

    for task in tasks:
        task_rows: list[dict[str, object]] = []
        for i in range(runs):
            result, events, diff_text = runner.run(
                task, agent_name, _config_for(task), run_id=f"{run_id}-{task.name}-{i}"
            )
            scoring_details: dict[str, str] = {}
            if out_dir is not None:
                from tooltrace.scoring.composite import score_task

                # Re-derive details cheaply from the trace validation event.
                for e in events:
                    if e.type == "validation" and isinstance(e.payload.get("details"), dict):
                        scoring_details = {str(k): str(v) for k, v in e.payload["details"].items()}
                        break
                _ = score_task  # keep import meaningful for type checkers
                write_bundle(out_dir, result, events, task, diff_text, scoring_details)
                result.bundle_path = (
                    f"{result.task_id.replace('/', '-')}-{agent_name}-{result.run_id}.tooltrace"
                )
            row: dict[str, object] = {
                "success": result.success,
                "partial_success": result.partial_success,
                "steps": result.steps,
                "tool_calls": result.tool_calls,
                "failed_tool_calls": result.failed_tool_calls,
                "wall_ms": result.wall_ms,
            }
            if task.perturbations:
                row["recovered"] = bool(
                    result.success
                )  # perturbation tasks define recovery as completing despite faults
            else:
                row["recovered"] = None
            task_rows.append(row)
            all_results.append(result)

        summary = summarize_reliability(task_rows)
        per_task_summary[task.id] = summary

    overall = summarize_reliability(
        [
            {
                "success": r.success,
                "partial_success": r.partial_success,
                "steps": r.steps,
                "tool_calls": r.tool_calls,
                "failed_tool_calls": r.failed_tool_calls,
                "wall_ms": r.wall_ms,
                "recovered": None,
            }
            for r in all_results
        ]
    )
    return BenchmarkRun(
        run_id=run_id,
        created_at=datetime.now(UTC).isoformat(),
        config={
            "agent": agent_name,
            "agent_config": dict(agent_config or {}),
            "runs_per_task": runs,
            "tasks": [t.id for t in tasks],
        },
        compatibility_key=compatibility_key(),
        results=all_results,
        summary={"overall": overall, "per_task": per_task_summary},
    )
