"""Generate static JSON indexes for the frontend from validated bundles.

Reads every *.tooltrace bundle under results/, verifies checksums, and writes:

    web/public/data/index.json      counts + metadata
    web/public/data/tasks.json      task summaries
    web/public/data/results.json    per-run rows
    web/public/data/agents.json     per-agent aggregates
    web/public/bundles/<name>/trace.json + workspace.diff.txt

Only verified bundles are included — no fabricated data.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.artifacts.bundles import load_bundle_result, read_manifest, verify_bundle
from tooltrace.core.versions import FRAMEWORK_VERSION

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
WEB_PUBLIC = ROOT / "web" / "public"


def _cost_axis(results: list) -> dict[str, object]:
    """Cost per resolved task, or nulls when no adapter reported spend."""
    from tooltrace.metrics.economics import cost_summary

    summary = cost_summary([r.model_dump(mode="json") for r in results])
    return {
        "cost_per_resolved_task": summary["cost_per_resolved_task"],
        "total_cost": summary["total_cost"],
        "priced_runs": summary["priced_runs"],
        "currency": summary["currency"],
    }


def _security_axis(results: list) -> dict[str, object]:
    """Attack-success rate, or null while no security pack ships.

    `docs/feature-status.md` row 16 is graded `S`: the security domain is
    declarable and no pack ships, so there is nothing to measure yet. Reporting
    `0.0` here would render as a perfect security score for an agent nobody has
    attacked, which is the most misleading number this dashboard could show.
    """
    security_runs = [r for r in results if str(r.task_id).startswith("security/")]
    if not security_runs:
        return {"attack_success_rate": None, "security_runs": 0}
    resisted = sum(1 for r in security_runs if r.success)
    return {
        "attack_success_rate": round(1 - resisted / len(security_runs), 6),
        "security_runs": len(security_runs),
    }


def main() -> int:
    bundles = sorted(RESULTS.glob("*.tooltrace"))
    results_rows: list[dict] = []
    tasks: dict[str, dict] = {}
    per_agent: dict[str, list] = defaultdict(list)
    skipped = 0

    for bundle in bundles:
        problems = verify_bundle(bundle)
        if problems:
            skipped += 1
            continue
        result = load_bundle_result(bundle)
        results_rows.append(
            {
                "bundle": bundle.name,
                "task_id": result.task_id,
                "task_version": result.task_version,
                "agent": result.agent,
                "success": result.success,
                "partial_success": result.partial_success,
                "score_total": result.score.total,
                "steps": result.steps,
                "tool_calls": result.tool_calls,
                "failed_tool_calls": result.failed_tool_calls,
                "invalid_tool_calls": result.invalid_tool_calls,
                "repeated_calls": result.repeated_calls,
                "unnecessary_changes": result.unnecessary_changes,
                "workspace_violations": result.workspace_violations,
                "wall_ms": result.wall_ms,
                "model_ms": result.model_ms,
                "tool_ms": result.tool_ms,
                "failure_reason": result.failure_reason.value,
                "trust_state": result.trust_state.value,
                "run_id": result.run_id,
                "created_at": result.finished_at,
            }
        )
        tasks.setdefault(
            result.task_id,
            {
                "id": result.task_id,
                "version": result.task_version,
                "category": result.task_id.split("/")[0],
                "difficulty": "medium",
                "tags": [],
                "max_steps": 0,
                "perturbations": [],
            },
        )
        per_agent[result.agent].append(result)

        # raw per-bundle data for the result detail page
        out = WEB_PUBLIC / "bundles" / bundle.name
        out.mkdir(parents=True, exist_ok=True)
        trace_lines = [
            json.loads(line)
            for line in (bundle / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        (out / "trace.json").write_text(json.dumps(trace_lines), encoding="utf-8")
        (out / "workspace.diff.txt").write_text(
            (bundle / "workspace.diff").read_text(encoding="utf-8"), encoding="utf-8"
        )

    agents_rows = []
    for agent, rs in sorted(per_agent.items()):
        walls = sorted(r.wall_ms for r in rs)
        p95 = walls[min(len(walls) - 1, int(0.95 * len(walls)))]
        agents_rows.append(
            {
                "name": agent,
                "runs": len(rs),
                "success_rate": sum(1 for r in rs if r.success) / len(rs),
                "mean_score": sum(r.score.total for r in rs) / len(rs),
                "mean_steps": sum(r.steps for r in rs) / len(rs),
                "failed_tool_calls_mean": sum(r.failed_tool_calls for r in rs) / len(rs),
                "wall_ms_p95": p95,
                # The four-axis view: accuracy is above, latency is p95, cost and
                # security follow. Each is null when unmeasured rather than 0,
                # so an axis nobody measured never reads as a perfect score.
                **_cost_axis(rs),
                **_security_axis(rs),
            }
        )

    data_dir = WEB_PUBLIC / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "index.json").write_text(
        json.dumps(
            {
                "generated_at": max((r["created_at"] for r in results_rows), default=""),
                "framework_version": FRAMEWORK_VERSION,
                "compatibility_key": read_manifest(bundles[0]).get("compatibility_key")
                if bundles
                else "",
                "counts": {
                    "tasks": len(tasks),
                    "results": len(results_rows),
                    "agents": len(agents_rows),
                    "packs": len({t["category"] for t in tasks.values()}),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_dir / "tasks.json").write_text(
        json.dumps(sorted(tasks.values(), key=lambda t: t["id"]), indent=2), encoding="utf-8"
    )
    (data_dir / "results.json").write_text(json.dumps(results_rows, indent=2), encoding="utf-8")
    (data_dir / "agents.json").write_text(json.dumps(agents_rows, indent=2), encoding="utf-8")
    print(
        f"web data: {len(results_rows)} results, {len(tasks)} tasks, "
        f"{len(agents_rows)} agents, {skipped} bundles skipped (failed verification)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
