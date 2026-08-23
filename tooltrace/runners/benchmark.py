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


def context_sweep(
    tasks: list,
    agent_name: str,
    agent_config: dict[str, object] | None = None,
    runs: int = 1,
    out_dir: Path | None = None,
) -> dict[str, object]:
    """Long-context sweep (§10): run a scale family of long-context tasks and
    report reliability/steps/latency per context size.

    Tasks must carry ``long_context=True`` and ``metadata.context_chars``.
    Returns ``{"sizes": [...], "per_size": {chars: summary}, "degradation": {...}}``
    where ``degradation`` compares the largest size against the smallest.
    """
    family = [t for t in tasks if getattr(t, "long_context", False)]
    missing = [t.id for t in tasks if not getattr(t, "long_context", False)]
    if missing:
        raise ValueError(
            "context_sweep requires long-context tasks; not marked long_context: "
            + ", ".join(sorted(missing))
        )
    by_chars: dict[int, list] = {}
    for t in family:
        chars = int(t.metadata.get("context_chars", 0))  # type: ignore[arg-type]
        by_chars.setdefault(chars, []).append(t)

    per_size: dict[str, dict[str, object]] = {}
    for chars in sorted(by_chars):
        bench = run_benchmark(by_chars[chars], agent_name, agent_config, runs=runs, out_dir=out_dir)
        per_size[str(chars)] = {
            "task_ids": [t.id for t in by_chars[chars]],
            **bench.summary.get("overall", {}),  # type: ignore[arg-type]
        }

    sizes = sorted(per_size, key=int)
    degradation: dict[str, object] = {}
    if len(sizes) >= 2:
        small, large = per_size[sizes[0]], per_size[sizes[-1]]
        for metric in ("rate", "steps_mean", "wall_ms_p95"):
            s_val, l_val = small.get(metric), large.get(metric)  # type: ignore[attr-defined]
            if isinstance(s_val, (int, float)) and isinstance(l_val, (int, float)) and s_val:
                degradation[metric] = {
                    "smallest": s_val,
                    "largest": l_val,
                    "delta_pct": round((l_val - s_val) / s_val * 100.0, 2),
                }
    return {"sizes": sizes, "per_size": per_size, "degradation": degradation}
