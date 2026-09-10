"""Generate static JSON indexes for the frontend from validated bundles.

Reads every *.tooltrace bundle under results/, verifies checksums, and writes:

    web/public/data/index.json      counts + metadata
    web/public/data/tasks.json      task summaries
    web/public/data/results.json    per-run rows
    web/public/data/agents.json     per-agent aggregates
    web/public/bundles/<name>/trace.json + workspace.diff.txt

Only verified bundles are included — no fabricated data.

Each failed run also carries `failure_step`: the seq and tool the failure is
attributed to, computed by the same `tooltrace.metrics.aggregate.failure_step`
the benchmark summary uses. It is what turns the dashboard's failure view from
a bar chart of categories into something a reader can open at the exact step.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.analysis.evidence import build_dossier
from tooltrace.artifacts.bundles import (
    load_bundle_result,
    load_bundle_task,
    load_bundle_trace,
    read_manifest,
    verify_bundle,
)
from tooltrace.core.versions import FRAMEWORK_VERSION
from tooltrace.metrics.aggregate import failure_step
from tooltrace.metrics.economics import cost_accuracy_points, pareto_frontier
from tooltrace.metrics.security import attack_class_of, attack_success_rate
from tooltrace.reports.badge import from_bundles as badge_from_bundles
from tooltrace.reports.badge import render_endpoint, render_svg

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
WEB_PUBLIC = ROOT / "web" / "public"


def _identity(result) -> str:
    """What the leaderboard treats as one competitor.

    The adapter name alone is wrong: `openai_compat` drives Ollama, llama.cpp,
    LM Studio, vLLM and SGLang, so every local model in a sweep landed on one
    row named after the adapter. The model is the thing being compared.

    A run that declares no model keeps the bare adapter name rather than
    acquiring an invented one -- "(unknown)" appended to every scripted run
    would be noise, and pretending a model was declared would be worse.
    """
    config = result.agent_config or {}
    model = str(config.get("model") or "").strip()
    return f"{result.agent} · {model}" if model else str(result.agent)


def generated_at_stamp(results_rows: list[dict]) -> str:
    return max((r["created_at"] for r in results_rows), default="")


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


def _security_axis(results: list, metadata_by_task: dict[str, dict]) -> dict[str, object]:
    """Attack-success rate, with the interval and the small-sample flag.

    Derived by `tooltrace.metrics.security.attack_success_rate` rather than
    recomputed here, so the dashboard and the CLI cannot disagree about how
    resistant an agent is.

    Null, never zero, when no security task ran: an unmeasured attack-success
    rate rendered as 0% reads as a perfectly secure agent, which is the most
    misleading number this dashboard could show.
    """
    security_runs = [r for r in results if str(r.task_id).startswith("security/")]
    if not security_runs:
        return {
            "attack_success_rate": None,
            "security_runs": 0,
            "attack_ci95": None,
            "security_sample_is_small": False,
        }
    block = attack_success_rate(
        [r.model_dump(mode="json") for r in security_runs], metadata_by_task
    )
    return {
        "attack_success_rate": block["attack_success_rate"],
        "security_runs": block["attempts"],
        "attack_ci95": block["ci95"],
        # 0% over four attempts is not evidence of a secure agent, and the
        # dashboard has to be able to say so.
        "security_sample_is_small": block["sample_is_small"],
    }


def _security_posture(
    results_by_agent: dict[str, list], metadata_by_task: dict[str, dict], rows: list[dict]
) -> dict[str, object]:
    """The security-posture index: overall, per attack class, and per run.

    Per-run records carry the timestamp so the view can show movement over time
    rather than a single number, and the attack class and OWASP reference so a
    reader can tell *what* was attempted, not only whether it worked.
    """
    security_rows = [r for r in rows if str(r["task_id"]).startswith("security/")]
    all_runs = [r for rs in results_by_agent.values() for r in rs]
    security_results = [r for r in all_runs if str(r.task_id).startswith("security/")]
    if not security_results:
        return {
            "attempts": 0,
            "attack_success_rate": None,
            "by_class": {},
            "by_agent": {},
            "runs": [],
        }

    overall = attack_success_rate(
        [r.model_dump(mode="json") for r in security_results], metadata_by_task
    )
    by_agent = {
        agent: attack_success_rate(
            [r.model_dump(mode="json") for r in rs if str(r.task_id).startswith("security/")],
            metadata_by_task,
        )
        for agent, rs in sorted(results_by_agent.items())
        if any(str(r.task_id).startswith("security/") for r in rs)
    }
    runs = []
    for row in sorted(security_rows, key=lambda r: str(r["created_at"])):
        metadata = metadata_by_task.get(str(row["task_id"]), {})
        attack = metadata.get("attack") if isinstance(metadata.get("attack"), dict) else {}
        runs.append(
            {
                "bundle": row["bundle"],
                "task_id": row["task_id"],
                "agent": row["agent"],
                "created_at": row["created_at"],
                # The scorers score the *defence*, so a failed run is a
                # successful attack. Naming it this way round in the index
                # means no reader has to remember the inversion.
                "attack_succeeded": not row["success"],
                "attack_class": attack_class_of(metadata),
                "vector": str(attack.get("vector") or ""),
                "owasp": str(attack.get("owasp") or ""),
            }
        )
    return {**overall, "by_agent": by_agent, "runs": runs}


def main() -> int:
    # Published bundles are replaced, not accumulated. Appending left traces
    # from deleted runs served alongside the current index, so the site could
    # hand out a trace for a bundle that no longer appears in any result row.
    shutil.rmtree(WEB_PUBLIC / "bundles", ignore_errors=True)

    bundles = sorted(RESULTS.glob("*.tooltrace"))
    results_rows: list[dict] = []
    tasks: dict[str, dict] = {}
    per_agent: dict[str, list] = defaultdict(list)
    # Task metadata carries the declared attack class, which is what turns a
    # failed security run into "an exfiltration attempt succeeded".
    metadata_by_task: dict[str, dict] = {}
    verified_bundles: list[Path] = []
    skipped = 0

    for bundle in bundles:
        problems = verify_bundle(bundle)
        if problems:
            skipped += 1
            continue
        result = load_bundle_result(bundle)
        # Where the failure happened, not just what class it was. Computed from
        # the same helper the benchmark summary uses, so the dashboard and the
        # CLI can never disagree about which step broke.
        events = load_bundle_trace(bundle)
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
                "failure_step": failure_step(result, events),
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
        # Keyed by adapter *and* model, not adapter alone. Five local models
        # all run through `openai_compat`, so grouping by adapter collapsed
        # them into a single leaderboard row named after the adapter -- a
        # leaderboard that cannot tell Qwen from Llama is not a leaderboard.
        per_agent[_identity(result)].append(result)
        verified_bundles.append(bundle)
        try:
            metadata_by_task.setdefault(result.task_id, dict(load_bundle_task(bundle).metadata))
        except Exception:
            # A bundle whose task will not parse still counts as a run; it just
            # has no declared attack class. Dropping the run would understate
            # how many attacks were attempted.
            metadata_by_task.setdefault(result.task_id, {})

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
                # The parts as well as the label, so a view can group by either
                # without re-parsing a display string.
                "adapter": rs[0].agent,
                "model": (rs[0].agent_config or {}).get("model") or None,
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
                **_security_axis(rs, metadata_by_task),
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

    # The cost/accuracy frontier. `pareto_frontier` had no caller outside the
    # tests, so the question it answers -- which agents is nobody beating on both
    # axes at once -- could be computed and never asked. Unpriced agents are
    # carried as points and excluded from the frontier, because a frontier that
    # silently ranked an unpriced agent as cheapest would be worse than none.
    # The same identity the leaderboard uses. Two views that disagree about who
    # the competitors are would put an agent on the frontier that the
    # leaderboard does not list.
    points = cost_accuracy_points(
        {agent: [r.model_dump(mode="json") for r in rs] for agent, rs in per_agent.items()}
    )
    frontier = pareto_frontier(points)
    (data_dir / "pareto.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at_stamp(results_rows),
                "points": points,
                "frontier": frontier,
                "unpriced": [p["agent"] for p in points if p["cost_per_resolved_task"] is None],
                "statement": (
                    "a frontier drawn from one agent names that agent and means nothing"
                    if len(points) < 2
                    else f"{len(frontier)} of {len(points)} agents are on the frontier; "
                    "the rest are beaten on both accuracy and cost at once"
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    generated_at = max((r["created_at"] for r in results_rows), default="")
    (data_dir / "security.json").write_text(
        json.dumps(
            {
                "generated_at": generated_at,
                **_security_posture(per_agent, metadata_by_task, results_rows),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # The reliability badge, so this project's own README can carry the number
    # it publishes rather than a hand-typed one that drifts. Colour comes from
    # the interval's lower bound, so a badge can never be greener than the
    # sample supports.
    badge_dir = WEB_PUBLIC / "badge"
    badge_dir.mkdir(parents=True, exist_ok=True)
    facts = badge_from_bundles(verified_bundles)
    (badge_dir / "reliability.svg").write_text(render_svg(facts), encoding="utf-8")
    (badge_dir / "reliability.json").write_text(
        json.dumps(render_endpoint(facts), indent=2), encoding="utf-8"
    )

    # The evidence dossier, dated from the newest run rather than the clock, so
    # regenerating the site twice produces byte-identical output and the hash
    # chain over it stays stable.
    (data_dir / "evidence.json").write_text(
        json.dumps(
            build_dossier(verified_bundles, generated_at=generated_at or "unknown"), indent=2
        ),
        encoding="utf-8",
    )
    print(
        f"web data: {len(results_rows)} results, {len(tasks)} tasks, "
        f"{len(agents_rows)} agents, {skipped} bundles skipped (failed verification)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
