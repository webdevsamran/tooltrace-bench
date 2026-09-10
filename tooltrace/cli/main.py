"""ToolTrace Bench CLI.

Commands: doctor, agents, tasks, run, benchmark, showdown, compare, baseline,
regression, validate, reproduce, report, export, serve, lint, dry-run,
self-test, snapshot, server, perturb, trace, task (scaffold/validate/test).

Every command supports ``--json`` for structured output and fails with
actionable messages and stable exit codes:
    0 ok | 2 usage error | 3 task/validation error | 4 agent error
    5 run failure | 8 regression threshold failed | 9 secrets detected
"""

from __future__ import annotations

import argparse
import contextlib
import json
import random
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tooltrace.core.exceptions import BundleError

if TYPE_CHECKING:
    from tooltrace.core.models import TaskDefinition

# Every subcommand handler takes the parsed namespace and returns an exit code.
CommandHandler = Callable[[argparse.Namespace], int]

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_TASK = 3
EXIT_AGENT = 4
EXIT_RUN = 5
EXIT_REGRESSION = 8


def _emit(data: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        print(data)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    import platform

    from tooltrace.agents.tool_schemas import coverage as tool_schema_coverage
    from tooltrace.core.registry import (
        ENTRY_POINT_GROUPS,
        agent_registry,
        discover_plugins,
        load_all_registries,
        sandbox_registry,
        scorer_registry,
        tool_registry,
    )
    from tooltrace.core.schemas import load_all_schemas, schema_source
    from tooltrace.tasks import load_all_tasks

    # This imported agents, scoring and tools by hand and omitted sandbox, so
    # `sandbox_registry` was always empty and a command described as a registry
    # health check never reported the sandbox providers at all. The helper
    # written to load all four had no caller; using it is the fix, and it means
    # a fifth registry cannot be forgotten here again.
    load_all_registries()

    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "tools": sorted(tool_registry.names()),
        # A tool with no declared schema is unchecked, not broken -- but
        # "nothing is validated" and "everything passed validation" look
        # identical from outside, so the count is reported here.
        "tool_schemas": tool_schema_coverage()["statement"],
        "agents": sorted(agent_registry.names()),
        "scorers": sorted(scorer_registry.names()),
        "sandboxes": sorted(sandbox_registry.names()),
        "plugins": {
            kind: sorted(discover_plugins(group)) for kind, group in ENTRY_POINT_GROUPS.items()
        },
        # A broken install should say so here rather than as a TaskValidationError
        # on every single task; see tooltrace/core/schemas.py.
        "schema_source": str(schema_source() or ""),
        "schemas_loaded": sorted(load_all_schemas()),
    }
    try:
        tasks = load_all_tasks()
        checks["tasks_loaded"] = len(tasks)
        checks["task_packs"] = len({t.pack for t in tasks})
    except Exception as exc:
        checks["tasks_loaded"] = f"ERROR: {exc}"
    ok = isinstance(checks["tasks_loaded"], int) and checks["tasks_loaded"] > 0
    _emit({"ok": ok, **checks}, args.json)
    return EXIT_OK if ok else EXIT_TASK


def _agent_config(value: str | None) -> dict[str, object] | None:
    """Adapter config from `--agent-config`: inline JSON, or `@path` to a file.

    `@path` exists because `tooltrace init` writes a config file, and a
    generated file that no command can read is a file that teaches the user
    nothing. It also keeps a long config out of shell history and out of the
    quoting rules of whichever shell the caller is in, which differ.
    """
    if not value:
        return None
    from tooltrace.cli.init import _agent_config_from

    try:
        return _agent_config_from(value)
    except FileNotFoundError:
        raise SystemExit(f"agent config file not found: {value[1:]}") from None
    except json.JSONDecodeError as exc:
        source = f"{value[1:]}: " if value.startswith("@") else ""
        raise SystemExit(f"agent config is not valid JSON: {source}{exc}") from None


def cmd_init(args: argparse.Namespace) -> int:
    from tooltrace.cli.init import run_init

    code, payload = run_init(
        Path(args.dir),
        adapter=args.agent,
        command=args.command or "",
        base_url=args.base_url or "",
        model=args.model or "",
        api_key_env=args.api_key_env or "",
        task=args.task or "",
        write_workflow=not args.no_ci,
        ci_system=args.ci,
        force=args.force,
        do_verify=not args.no_run,
    )
    if code != EXIT_OK:
        for problem in payload.get("problems", []):
            print(problem, file=sys.stderr)
        _emit(payload, args.json)
        return EXIT_USAGE
    _emit(payload if args.json else payload["report"], args.json)
    return EXIT_OK


def cmd_badge(args: argparse.Namespace) -> int:
    from tooltrace.reports.badge import (
        embed_markdown,
        from_bundles,
        from_summary_file,
        render_endpoint,
        render_svg,
    )

    if args.summary:
        facts = from_summary_file(Path(args.summary))
    elif args.bundles:
        facts = from_bundles(sorted(Path(args.bundles).glob("*.tooltrace")))
    else:
        print("badge needs --summary or --bundles", file=sys.stderr)
        return EXIT_USAGE

    svg = render_svg(facts)
    endpoint = render_endpoint(facts)
    written: list[str] = []
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(svg, encoding="utf-8")
        written.append(str(out))
        endpoint_path = out.with_suffix(".json")
        endpoint_path.write_text(json.dumps(endpoint, indent=2), encoding="utf-8")
        written.append(str(endpoint_path))

    payload = {
        "facts": facts,
        "endpoint": endpoint,
        "written": written,
        "embed": embed_markdown(
            args.svg_url or (written[0] if written else "badge.svg"), args.link or ""
        ),
        "svg": svg if not args.out else "",
    }
    if args.json:
        _emit(payload, True)
    elif args.out:
        print(chr(10).join(written))
        print(payload["embed"])
    else:
        print(svg)
    return EXIT_OK


def cmd_pr_report(args: argparse.Namespace) -> int:
    from tooltrace.analysis.pr_report import (
        cohort_problems,
        compare_samples,
        render_markdown,
        rows_from_bundles,
    )

    baseline_dir, current_dir = Path(args.baseline), Path(args.current)
    baseline_rows, baseline_meta = rows_from_bundles(list(baseline_dir.glob("*.tooltrace")))
    current_rows, current_meta = rows_from_bundles(list(current_dir.glob("*.tooltrace")))
    if not baseline_rows or not current_rows:
        print("pr-report needs bundles on both sides", file=sys.stderr)
        return EXIT_USAGE

    # `--metrics` exists for shared CI runners. `wall_ms` is wall-clock, and a
    # noisy neighbour on the runner is not a change in the agent -- a gate that
    # fails for that reason gets switched off, which costs the four metrics that
    # were worth gating on. Narrowing the gate is better than losing it.
    wanted = [m.strip() for m in args.metrics.split(",") if m.strip()] if args.metrics else None
    report = compare_samples(baseline_rows, current_rows, metrics=wanted)
    # A comparison across different task sets or artifact versions attributes a
    # difference in measurement to the code. Refused, not annotated.
    report.incomparable.extend(cohort_problems(baseline_meta, current_meta))
    markdown = render_markdown(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(markdown, encoding="utf-8")

    if args.json:
        _emit({**report.to_dict(), "markdown": markdown}, True)
    else:
        print(markdown)

    if report.incomparable:
        return EXIT_USAGE
    # Only an established regression fails. An inconclusive comparison is
    # reported loudly and does not block: failing on absent evidence would make
    # this gate a function of the caller's compute budget.
    return EXIT_REGRESSION if report.regressed else EXIT_OK


def cmd_power(args: argparse.Namespace) -> int:
    """What a planned sweep can detect, before spending anything on it."""
    from tooltrace.analysis.power import power_report, runs_for_effect

    if args.detect is not None:
        needed = runs_for_effect(args.detect, baseline_rate=args.baseline_rate)
        if needed is None:
            print("--detect needs a positive difference", file=sys.stderr)
            return EXIT_USAGE
        payload: dict[str, object] = {
            "detect": args.detect,
            "baseline_rate": args.baseline_rate,
            "runs_per_arm": needed,
            "statement": (
                f"Detecting a {args.detect * 100:.1f} point difference at a "
                f"{args.baseline_rate:.2f} baseline needs about {needed} runs per arm."
            ),
        }
        _emit(payload if args.json else payload["statement"], args.json)
        return EXIT_OK

    report = power_report(args.runs, baseline_rate=args.baseline_rate)
    if args.json:
        _emit(report, True)
    else:
        print(report["statement"])
        print()
        for effect, needed in report["runs_needed_for"].items():
            print(f"  to detect {float(effect) * 100:>4.0f} points: {needed} runs per arm")
        print()
        print(report["assumption"])
    return EXIT_OK


def cmd_cost(args: argparse.Namespace) -> int:
    """Where the money went, what a planned sweep would cost, and whether it pays."""

    from tooltrace.artifacts.bundles import load_bundle_result
    from tooltrace.metrics.budget import cost_attribution, forecast_spend, viability_verdict
    from tooltrace.metrics.economics import cost_accuracy_points, cost_summary, pareto_frontier

    bundles = sorted(Path(args.bundles).glob("*.tooltrace"))
    if not bundles:
        print(f"no bundles under {args.bundles}", file=sys.stderr)
        return EXIT_USAGE
    results = [load_bundle_result(b).model_dump(mode="json") for b in bundles]

    summary = cost_summary(results)
    attribution: dict[str, Any] = cost_attribution(results)
    forecast: dict[str, Any] | None = None
    if args.forecast_tasks and args.forecast_runs:
        forecast = forecast_spend(
            tasks=args.forecast_tasks, runs_per_task=args.forecast_runs, observed=results
        )
    viability: dict[str, Any] = viability_verdict(
        cost_per_resolved_task=summary.get("cost_per_resolved_task"),
        human_baseline_cost=args.human_baseline,
        success_rate=(
            sum(1 for r in results if r.get("success")) / len(results) if results else None
        ),
        currency=str(summary.get("currency") or "USD"),
    )

    # The frontier had no caller outside the tests, so the question it answers --
    # "which agents is nobody beating on both axes at once" -- could be computed
    # and never asked. A single-agent run has a frontier of one, which is true
    # and useless, so the payload says how many arms it was drawn from.
    per_agent: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        per_agent.setdefault(str(result.get("agent") or "unknown"), []).append(result)
    points = cost_accuracy_points(per_agent)
    frontier = pareto_frontier(points)

    payload: dict[str, Any] = {
        "runs": len(results),
        "summary": summary,
        "attribution": attribution,
        "viability": viability,
        "cost_accuracy": {
            "points": points,
            "frontier": frontier,
            "agents": len(points),
            "statement": (
                "a frontier drawn from one agent names that agent and means nothing"
                if len(points) < 2
                else f"{len(frontier)} of {len(points)} agents are on the frontier; "
                "the rest are beaten on both accuracy and cost at once"
            ),
        },
    }
    if forecast is not None:
        payload["forecast"] = forecast

    if args.json:
        _emit(payload, True)
        return EXIT_OK

    if not attribution.get("measurable"):
        print(attribution.get("reason"))
    else:
        print(f"total {attribution['total']} over {len(results)} run(s)")
        print(
            f"spent on failures: {attribution['spent_on_failures']} "
            f"({attribution['failure_share']:.1%})"
        )
        if not attribution.get("covers_all_runs"):
            print(f"  note: {attribution['unpriced_runs']} run(s) reported no cost")

    if len(points) >= 2:
        print()
        print("cost vs accuracy:")
        for point in sorted(points, key=lambda p: -p["success_rate"]):
            mark = "frontier" if point["agent"] in frontier else "dominated"
            cost = point["cost_per_resolved_task"]
            cost_text = f"{cost}" if cost is not None else "unpriced"
            print(f"  {mark:<10} {point['agent']:<24} {point['success_rate']:.1%} @ {cost_text}")

    if forecast is not None:
        print()
        if forecast.get("measurable"):
            print(
                f"forecast {forecast['estimate']} {forecast['currency']} "
                f"for {forecast['planned_runs']} runs"
            )
            print(f"  range {forecast['range'][0]}-{forecast['range'][1]}")
            print(f"  {forecast['assumption']}")
        else:
            print(f"forecast unavailable: {forecast['reason']}")

    print()
    if viability.get("measurable"):
        print(f"viability: {viability['verdict']} (ratio {viability['ratio']})")
        for assumption in viability["assumptions"]:
            print(f"  - {assumption}")
    else:
        print(f"viability: {viability['reason']}")
    return EXIT_OK


def cmd_owasp(args: argparse.Namespace) -> int:
    """OWASP Agentic Top 10 coverage, computed from packs that run here."""
    from tooltrace.security.coverage import coverage_matrix, render_markdown

    matrix = coverage_matrix()
    if args.json:
        _emit(matrix, True)
    elif args.markdown:
        print(render_markdown(matrix), end="")
    else:
        for row in matrix["categories"]:
            tasks = ", ".join(row["tasks"]) or "-"
            print(f"{row['id']}  {row['status']:<14} {row['label']:<42} {tasks}")
        print()
        print(matrix["statement"])
    return EXIT_OK


def cmd_attest(args: argparse.Namespace) -> int:
    """Reproduce a bundle and record an attestation, or read the ones it has.

    The trust ladder in `TrustState` promises four levels "never implied without
    evidence", and every bundle this project has written is `LOCAL`:
    `promote_trust` had no caller outside the tests. An attestation is the
    missing evidence, and this command is where it comes from.
    """

    from tooltrace.analysis.attestation import (
        build_attestation,
        machine_relation,
        promotion_for,
        render_markdown,
        verify_attestation,
    )

    bundle = Path(args.bundle)
    if not bundle.is_dir():
        print(f"not a bundle directory: {bundle}", file=sys.stderr)
        return EXIT_USAGE

    store = bundle / "attestations.jsonl"
    existing: list[dict[str, Any]] = []
    if store.is_file():
        for line in store.read_text(encoding="utf-8").splitlines():
            if line.strip():
                existing.append(json.loads(line))

    if args.attester:
        from tooltrace.artifacts.bundles_repro import reproduce_bundle

        report = reproduce_bundle(bundle, out_dir=None, rerun=True)
        reproduced = bool(report.verified and report.rerun_success)
        attestation = build_attestation(
            bundle,
            attester=args.attester,
            attested_at=args.at or datetime.now(UTC).isoformat(),
            reproduced=reproduced,
            detail=report.message or "",
            signature=args.signature or "",
        )
        problems = verify_attestation(bundle, attestation)
        if problems:
            _emit({"ok": False, "problems": problems}, args.json)
            return EXIT_RUN
        # Appended, never rewritten: an attestation store that can be edited in
        # place is a store whose history nobody can check.
        with store.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(attestation, sort_keys=True) + chr(10))
        existing.append(attestation)

    for attestation in existing:
        attestation["_machine"] = machine_relation(bundle, attestation)
    promotion = promotion_for(bundle, existing)

    if args.promote:
        from tooltrace.artifacts.bundles_repro import promote_trust
        from tooltrace.core.models import TrustState

        promote_trust(bundle, TrustState(promotion["state"]))
        # Every attestation is bound to the manifest digest, which promotion
        # changes. Rewriting them would be forging them, so they are marked
        # stale instead and the reason says why.
        promotion["note"] = (
            promotion["note"]
            + " Promotion rewrites the manifest, so attestations made before it no longer "
            "match its digest. Re-attest after promoting."
        )

    payload = {
        "bundle": bundle.name,
        "attestations": existing,
        "promotion": promotion,
        "promoted": bool(args.promote),
    }
    if args.json:
        _emit(payload, True)
    else:
        print(render_markdown(bundle.name, existing, promotion), end="")
    return EXIT_OK


def cmd_card(args: argparse.Namespace) -> int:
    """A system card for one agent, generated from its recorded runs."""
    from tooltrace.analysis.system_card import build_card, render_card
    from tooltrace.artifacts.bundles import load_bundle_result
    from tooltrace.security.coverage import coverage_matrix

    bundles = sorted(Path(args.bundles).glob("*.tooltrace"))
    if not bundles:
        print(f"no bundles under {args.bundles}", file=sys.stderr)
        return EXIT_USAGE
    runs = [load_bundle_result(b).model_dump(mode="json") for b in bundles]

    agents = sorted({str(r.get("agent")) for r in runs})
    agent = args.agent or (agents[0] if len(agents) == 1 else "")
    if not agent:
        print(f"several agents present; pick one with --agent: {agents}", file=sys.stderr)
        return EXIT_USAGE

    security_runs = [r for r in runs if str(r.get("task_id", "")).startswith("security/")]
    card = build_card(
        runs,
        agent=agent,
        generated_at=args.at or max((str(r.get("finished_at") or "") for r in runs), default=""),
        security={"attempts": len(security_runs)},
        coverage=coverage_matrix(),
    )
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_card(card), encoding="utf-8")
    if args.json:
        _emit(card, True)
    else:
        print(render_card(card), end="")
    return EXIT_OK


def cmd_self_audit(args: argparse.Namespace) -> int:
    """Would the evidence you hold actually demonstrate anything?"""
    from tooltrace.analysis.attestation import machine_relation
    from tooltrace.analysis.system_card import audit_evidence
    from tooltrace.artifacts.bundles import load_bundle_result, verify_bundle
    from tooltrace.security.coverage import coverage_matrix

    bundles = sorted(Path(args.bundles).glob("*.tooltrace"))
    if not bundles:
        print(f"no bundles under {args.bundles}", file=sys.stderr)
        return EXIT_USAGE

    facts = []
    attested = 0
    independent = 0
    security_attempts = 0
    for bundle in bundles:
        facts.append({"bundle": bundle.name, "verified": not verify_bundle(bundle)})
        if str(load_bundle_result(bundle).task_id).startswith("security/"):
            security_attempts += 1
        store = bundle / "attestations.jsonl"
        if store.is_file():
            for line in store.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                attestation = json.loads(line)
                attested += 1
                if (
                    attestation.get("outcome") == "reproduced"
                    and machine_relation(bundle, attestation) == "different_machine"
                ):
                    independent += 1

    report = audit_evidence(
        bundles=facts,
        attested=attested,
        independently_attested=independent,
        security_attempts=security_attempts,
        coverage=coverage_matrix(),
    )
    if args.json:
        _emit(report, True)
    else:
        for check in report["checks"]:
            mark = "pass" if check["passed"] else "GAP "
            print(f"{mark}  {check['check']:<34} {check['detail']}")
        if report["gaps"]:
            print()
            print("Gaps:")
            for gap in report["gaps"]:
                print(f"  - {gap}")
        print()
        print(report["statement"])
    # A gap is a finding, not an error: this command reports on evidence, and
    # exiting non-zero would make it a gate nobody could ever pass.
    return EXIT_OK


def _rows_from(directory: str) -> list[dict[str, object]]:
    from tooltrace.artifacts.bundles import load_bundle_result

    rows: list[dict[str, object]] = []
    for bundle in sorted(Path(directory).glob("*.tooltrace")):
        result = load_bundle_result(bundle)
        rows.append(
            {
                "success": result.success,
                "steps": result.steps,
                "wall_ms": result.wall_ms,
                "failed_tool_calls": result.failed_tool_calls,
                "tool_calls": result.tool_calls,
                "task_id": result.task_id,
            }
        )
    return rows


def cmd_drift(args: argparse.Namespace) -> int:
    """Has behaviour moved between two windows of runs?"""
    from tooltrace.analysis.drift import compare_windows, error_budget

    current = _rows_from(args.current)
    if not current:
        print(f"no bundles under {args.current}", file=sys.stderr)
        return EXIT_USAGE

    payload: dict[str, object] = {}
    if args.baseline:
        baseline = _rows_from(args.baseline)
        if not baseline:
            print(f"no bundles under {args.baseline}", file=sys.stderr)
            return EXIT_USAGE
        payload["drift"] = compare_windows(baseline, current)
    if args.objective is not None:
        payload["error_budget"] = error_budget(current, objective=args.objective)
    if not payload:
        print("drift needs --baseline, --objective, or both", file=sys.stderr)
        return EXIT_USAGE

    if args.json:
        _emit(payload, True)
        return EXIT_OK

    drift = payload.get("drift")
    if isinstance(drift, dict):
        if not drift.get("measurable"):
            print(drift["reason"])
        else:
            for finding in drift["findings"]:
                print(
                    f"{finding['verdict']:<13} {finding['metric']:<20} "
                    f"{finding['baseline']:>10.4f} -> {finding['current']:<10.4f} "
                    f"{finding['note']}"
                )
            print()
            print(drift["statement"])
    budget = payload.get("error_budget")
    if isinstance(budget, dict):
        print()
        print(budget.get("statement") or budget.get("reason"))
    return EXIT_OK


def cmd_promote_trace(args: argparse.Namespace) -> int:
    """Turn a production trace into a draft regression task."""
    import yaml
    from tooltrace.core.models import TraceEvent
    from tooltrace.ingest.promote import promote_trace, readiness

    source = Path(args.trace)
    if not source.is_file():
        print(f"not a file: {source}", file=sys.stderr)
        return EXIT_USAGE

    events = [
        TraceEvent.model_validate(json.loads(line))
        for line in source.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not events:
        print("the trace is empty", file=sys.stderr)
        return EXIT_USAGE

    task = promote_trace(
        events, task_id=args.task_id, objective=args.objective or "", incident=args.incident or ""
    )
    report = readiness(task)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(task, sort_keys=False), encoding="utf-8")

    payload = {"task": task, "readiness": report, "written": str(args.out or "")}
    if args.json:
        _emit(payload, True)
    else:
        print(yaml.safe_dump(task, sort_keys=False), end="")
        print()
        for problem in report["problems"]:
            print(f"TODO: {problem}", file=sys.stderr)
        print(report["statement"], file=sys.stderr)
    # A draft is the expected output, so an unfinished one is not an error.
    return EXIT_OK


def cmd_backends(args: argparse.Namespace) -> int:
    """Local model servers this project knows, and which are listening."""
    from tooltrace.agents.local_backends import describe

    report = describe()
    if args.json:
        _emit(report, True)
        return EXIT_OK

    for row in report["backends"]:
        mark = "up  " if row["listening"] else "    "
        print(f"{mark}{row['backend']:<11} {row['base_url']:<32} {row['model_hint']}")
        print(f"      {row['note']}")
    print()
    if report["listening"]:
        print(f"listening on this machine: {', '.join(report['listening'])}")
        print("An open port is not a positive identification of the server.")
    else:
        print("nothing is listening on any known local port")
    print()
    print(report["statement"])
    return EXIT_OK


def cmd_a2a_card(args: argparse.Namespace) -> int:
    """Check an A2A Agent Card, and say what its signature does and does not prove."""
    from tooltrace.agents.a2a import report

    path = Path(args.card)
    if not path.is_file():
        print(f"error: no such card: {path}", file=sys.stderr)
        return EXIT_TASK
    try:
        card = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"error: {path} is not JSON: {exc}", file=sys.stderr)
        return EXIT_TASK
    if not isinstance(card, dict):
        print(f"error: {path} is not an object", file=sys.stderr)
        return EXIT_TASK

    keys: dict[str, bytes] | None = None
    if args.key:
        # From the caller, never from the card. A signature checked against a
        # key the document itself names proves the document agrees with itself.
        keys = {}
        for pair in args.key:
            kid, _, secret = pair.partition("=")
            keys[kid if secret else "default"] = (secret or kid).encode("utf-8")

    result = report(card, keys)
    if args.json:
        _emit(result, True)
    else:
        for check in result["checks"]:
            mark = "pass" if check["passed"] else "FAIL"
            print(f"  [{mark:>4}] {check['severity']:<11} {check['name']}: {check['detail']}")
        print()
        print(result["statement"])
    if result["required_failures"]:
        print(
            f"error: {len(result['required_failures'])} required field(s) missing",
            file=sys.stderr,
        )
        return EXIT_TASK
    return EXIT_OK


def cmd_mcp_scan(args: argparse.Namespace) -> int:
    """Score many MCP servers at once.

    `--from` reads a local file you wrote, whose entries may name a command.
    `--registry` fetches a list over the network, whose entries may not: running
    a command string that arrived from a server on the internet is remote code
    execution, and a reputable registry changes only how likely that is to be
    abused today. A fetched entry carrying a command is reported as skipped with
    the reason, because a silent drop reads as a pass.
    """
    from tooltrace.agents.mcp_scan import (
        LOCAL,
        REMOTE,
        render_markdown,
        scan,
        targets_from_registry,
    )

    if args.registry:
        import httpx

        try:
            response = httpx.get(args.registry, timeout=30.0)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            print(f"error: could not read {args.registry}: {exc}", file=sys.stderr)
            return EXIT_RUN
        targets, origin = targets_from_registry(payload), REMOTE
    else:
        path = Path(args.from_file)
        if not path.is_file():
            print(f"error: no such file: {path}", file=sys.stderr)
            return EXIT_TASK
        loaded = json.loads(path.read_text(encoding="utf-8"))
        targets = loaded if isinstance(loaded, list) else loaded.get("servers", [])
        origin = LOCAL

    if not targets:
        print("error: no servers to scan", file=sys.stderr)
        return EXIT_USAGE

    report = scan(targets, origin)
    if args.json:
        _emit(report, True)
    elif args.markdown:
        print(render_markdown(report), end="")
    else:
        for row in report["results"]:
            mark = "ok     " if row["ok"] else "PROBLEM"
            print(f"{mark} {row['name']:<40} {len(row['problems'])} problem(s)")
        for skipped in report["skipped"]:
            print(f"skipped {skipped['name']:<40} {skipped['reason']}")
        print()
        print(report["statement"])
    return EXIT_OK if report["ok"] else EXIT_RUN


def cmd_mcp_versions(args: argparse.Namespace) -> int:
    """Which MCP protocol revisions a server implements, and whether it checks."""
    from tooltrace.agents.mcp import fake_server_command
    from tooltrace.agents.mcp_versions import render_markdown, version_matrix

    if args.url:
        report = version_matrix(url=args.url)
    else:
        report = version_matrix(args.command or fake_server_command())
    if args.json:
        _emit(report, True)
    elif args.markdown:
        print(render_markdown(report), end="")
    else:
        for row in report["versions"]:
            mark = "PROBLEM" if row["problem"] else "ok     "
            print(f"{mark} sent {row['sent']:<12} -> {row['outcome']:<16} {row['detail']}")
        print()
        print(report["statement"])
    if report["problems"]:
        print(
            f"error: {len(report['problems'])} version(s) mishandled: {report['problems']}",
            file=sys.stderr,
        )
        return EXIT_RUN
    return EXIT_OK


def cmd_mcp_fuzz(args: argparse.Namespace) -> int:
    """Send malformed JSON-RPC at an MCP server and report what it did."""
    from tooltrace.agents.mcp import fake_server_command
    from tooltrace.agents.mcp_fuzz import fuzz, render_markdown

    command = args.command or fake_server_command()
    report = fuzz(command)
    if args.json:
        _emit(report, True)
    elif args.markdown:
        print(render_markdown(report), end="")
    else:
        for row in report["cases"]:
            mark = "PROBLEM" if row["problem"] else "ok     "
            print(f"{mark} {row['case']:<28} {row['severity']:<14} {row['outcome']}")
            if row["problem"]:
                print(f"        {row['why']}")
                print(f"        {row['detail']}")
        print()
        print(report["statement"])
    if report["problems"]:
        print(f"error: {len(report['problems'])} problem(s): {report['problems']}", file=sys.stderr)
        return EXIT_RUN
    return EXIT_OK


def cmd_agents(args: argparse.Namespace) -> int:
    from tooltrace.agents import AgentAdapter  # noqa: F401
    from tooltrace.core.registry import agent_registry

    rows = [
        {"name": n, "class": getattr(a, "__name__", str(a))}
        for n, a in sorted(agent_registry.items())
    ]
    _emit(rows if args.json else chr(10).join(r["name"] for r in rows), args.json)
    return EXIT_OK


def cmd_tools(args: argparse.Namespace) -> int:
    """What a model is actually told about the tools it may call.

    `agents` lists adapters; this lists the other side of the same
    conversation. `--dialect` renders the catalogue as a provider would receive
    it, which is the only way to check that a tool's schema survives the
    translation -- Gemini rejects half the JSON Schema keywords the others
    accept, and a request error is a poor way to find that out.
    """
    from tooltrace.agents.tool_schemas import coverage, present, render_prompt_block

    if args.equivalence:
        from tooltrace.agents.tool_equivalence import equivalence_report
        from tooltrace.agents.tool_equivalence import render_markdown as render_equivalence

        report = equivalence_report()
        _emit(report if args.json else render_equivalence(report).rstrip(), args.json)
        return EXIT_OK

    if args.dialect and args.dialect != "prompt":
        payload = present(None, args.dialect)
        _emit(payload if args.json else json.dumps(payload, indent=2), args.json)
        return EXIT_OK

    report = coverage()
    if args.json:
        _emit({**report, "catalogue": render_prompt_block()}, True)
    else:
        _emit(render_prompt_block() + chr(10) * 2 + report["statement"], False)
    return EXIT_OK


def cmd_tasks(args: argparse.Namespace) -> int:
    from tooltrace.tasks import load_all_tasks

    tasks = load_all_tasks()
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]
    from tooltrace.tasks.availability import availability

    rows = [
        {
            "id": t.id,
            "version": t.version,
            "category": t.category,
            "difficulty": t.difficulty.value,
            "runnable_here": availability(t).runnable,
            "requires_tools": t.requires_tools,
            "tags": t.tags,
            "max_steps": t.max_steps,
            "perturbations": [p.kind for p in t.perturbations],
        }
        for t in tasks
    ]
    if args.json:
        _emit(rows, True)
    else:
        for r in rows:
            print(f"{r['id']:<50} {r['category']:<22} {r['difficulty']}")
    return EXIT_OK


def cmd_run(args: argparse.Namespace) -> int:
    from tooltrace.artifacts.bundles import write_bundle
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks import find_task

    try:
        task = find_task(args.task)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_TASK

    # A task that needs a toolchain this machine lacks is skipped, not scored.
    # Recording it as a failure would make the result depend on the runner's
    # installed software rather than on the agent.
    from tooltrace.tasks.availability import availability

    state = availability(task)
    if not state.runnable:
        _emit(
            {
                "task_id": task.id,
                "skipped": True,
                "reason": state.reason,
                "missing_tools": list(state.missing),
            },
            args.json,
        )
        print(f"skipped {task.id}: {state.reason}", file=sys.stderr)
        return EXIT_OK

    agent_config = _agent_config(args.agent_config)
    if agent_config is None and args.agent == "scripted":
        script = task.metadata.get("scripted_script")
        if isinstance(script, list):
            agent_config = {"script": script}
    runner = TaskRunner(output_dir=Path(args.out) if args.out else None)
    result, events, diff_text = runner.run(task, args.agent, agent_config)
    payload = {"result": result.model_dump(mode="json"), "diff": diff_text}
    if args.out:
        details = {}
        for e in events:
            if e.type == "validation" and isinstance(e.payload.get("details"), dict):
                details = {str(k): str(v) for k, v in e.payload["details"].items()}
                break
        bundle = write_bundle(
            Path(args.out), result, events, task, diff_text, details, agent_config=agent_config
        )
        payload["bundle"] = bundle.name
    _emit(payload, args.json)
    return EXIT_OK if result.success else EXIT_RUN


def _select_tasks(
    tasks: list[TaskDefinition], args: argparse.Namespace
) -> tuple[list[TaskDefinition], dict[str, object]]:
    """Apply `--task`, `--shuffle` and `--limit`, and record what was chosen.

    Nobody runs a full benchmark on every pull request, so without a cheap
    subset the CI integration simply does not happen. The risk is that a
    truncated run reads like a full one, so the selection is returned alongside
    the tasks and recorded in the run config: which policy, which seed, how many
    of how many, and the exact ids. A subset is then reproducible by anyone with
    the same seed, and obviously a subset to anyone reading the output.
    """
    chosen = list(tasks)
    if getattr(args, "task", None):
        wanted = {t.strip() for t in str(args.task).split(",") if t.strip()}
        chosen = [t for t in chosen if t.id in wanted]

    available = len(chosen)
    limit = getattr(args, "limit", None)
    shuffle = bool(getattr(args, "shuffle", False))
    seed = getattr(args, "seed", None)

    policy = "all"
    effective_seed: int | None = None if seed is None else int(seed)
    if shuffle:
        # Sort first so the shuffle depends only on the seed, never on the
        # order the loader happened to walk the pack directories in.
        effective_seed = 0 if effective_seed is None else effective_seed
        chosen = sorted(chosen, key=lambda t: t.id)
        random.Random(effective_seed).shuffle(chosen)
        policy = "seeded_shuffle"

    if limit is not None and limit < len(chosen):
        if not shuffle:
            chosen = sorted(chosen, key=lambda t: t.id)
            policy = "first_by_id"
        chosen = chosen[:limit]

    selection: dict[str, object] = {
        "policy": policy,
        "seed": effective_seed,
        "requested_limit": limit,
        "available": available,
        "selected": len(chosen),
        "is_subset": len(chosen) < available,
        "task_ids": [t.id for t in chosen],
    }
    return chosen, selection


def cmd_benchmark(args: argparse.Namespace) -> int:
    from tooltrace.runners.benchmark import run_benchmark
    from tooltrace.tasks import load_all_tasks

    tasks = load_all_tasks()
    if getattr(args, "context_sweep", False):
        return _cmd_context_sweep(args, tasks)
    if args.task:
        wanted = set(args.task.split(","))
        missing = wanted - {t.id for t in tasks}
        if missing:
            print(f"error: unknown tasks: {sorted(missing)}", file=sys.stderr)
            return EXIT_TASK
    tasks, selection = _select_tasks(tasks, args)
    if not tasks:
        print("error: no tasks selected", file=sys.stderr)
        return EXIT_TASK
    if selection["is_subset"]:
        # A truncated run must never read like a full one.
        print(
            f"note: running {selection['selected']} of {selection['available']} tasks "
            f"(policy={selection['policy']}, seed={selection['seed']})",
            file=sys.stderr,
        )

    # Drop tasks this machine cannot run, and say which -- silently omitting
    # them would make the benchmark look complete when it was not, and scoring
    # them as failures would blame the agent for the runner's missing software.
    from tooltrace.tasks.availability import partition

    tasks, skipped = partition(tasks)
    for task, reason in skipped:
        print(f"skipping {task.id}: {reason}", file=sys.stderr)
    if not tasks:
        print(
            "error: every selected task requires tooling this machine lacks",
            file=sys.stderr,
        )
        return EXIT_TASK

    guard = None
    if getattr(args, "budget", None):
        from tooltrace.metrics.budget import BudgetGuard

        guard = BudgetGuard(ceiling=float(args.budget), currency=args.budget_currency)

    bench = run_benchmark(
        tasks,
        args.agent,
        _agent_config(args.agent_config),
        runs=args.runs,
        out_dir=Path(args.out) if args.out else None,
        budget=guard,
    )
    payload = bench.model_dump(mode="json")
    payload["selection"] = selection
    if guard is not None and guard.stopped:
        # Same discipline as the subset note above: a sweep cut short must never
        # read like a complete one, and stderr keeps stdout machine-readable.
        print(
            f"note: stopped by the budget after {guard.runs_completed} run(s); "
            f"{guard.runs_skipped} not run ({guard.stop_reason})",
            file=sys.stderr,
        )
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"benchmark-{bench.run_id}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    summary_only = {k: v for k, v in payload.items() if k != "results"}
    _emit(summary_only if args.summary else payload, args.json)
    rate = float(bench.summary.get("overall", {}).get("rate", 0.0))
    return EXIT_OK if rate >= args.min_success_rate else EXIT_RUN


def _cmd_context_sweep(args: argparse.Namespace, tasks: list[TaskDefinition]) -> int:
    """`benchmark --context-sweep`: reliability vs context size (§10)."""
    from tooltrace.runners.benchmark import context_sweep

    family = [t for t in tasks if getattr(t, "long_context", False)]
    if not family:
        print(
            "error: no long-context tasks found; add tasks with long_context: true",
            file=sys.stderr,
        )
        return EXIT_TASK
    try:
        sweep = context_sweep(
            family,
            args.agent,
            _agent_config(args.agent_config),
            runs=args.runs,
            out_dir=Path(args.out) if args.out else None,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RUN
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "context-sweep.json").write_text(json.dumps(sweep, indent=2), encoding="utf-8")
    _emit(sweep, args.json)
    return EXIT_OK


def cmd_showdown(args: argparse.Namespace) -> int:
    """Run one benchmark per agent and rank them -- but only when the sample supports it.

    This used to sort on the success-rate point estimate and stop. It carried a
    confidence interval in the payload and never looked at it, so two agents at
    ``--runs 1`` still came back in a definite order, and the repository shipped
    a statistics module whose whole purpose is to refuse exactly that claim
    (``significance_note`` declines to name a winner below n=30). Every function
    used below already existed in ``tooltrace/metrics/reliability.py``; none of
    them had a caller outside the test suite.

    Ranking is reported as provisional unless the sample is large enough *and*
    the leader's Wilson interval clears the runner-up's.
    """
    from tooltrace.metrics.reliability import (
        effect_size_cohens_h,
        paired_delta,
        significance_note,
    )
    from tooltrace.runners.benchmark import run_benchmark
    from tooltrace.tasks import load_all_tasks

    tasks, selection = _select_tasks(load_all_tasks(), args)
    if not tasks:
        print("error: no tasks selected", file=sys.stderr)
        return EXIT_TASK
    if selection["is_subset"]:
        print(
            f"note: running {selection['selected']} of {selection['available']} tasks "
            f"(policy={selection['policy']}, seed={selection['seed']})",
            file=sys.stderr,
        )
    agents = args.agents.split(",")

    standings: list[dict[str, object]] = []
    # Every agent runs the identical task list in the same order, so these
    # vectors are genuinely paired and paired_delta is legitimate.
    outcomes: dict[str, list[bool]] = {}
    # One row per run, keyed by (agent, task), for the variance split.
    variance_rows: list[dict[str, object]] = []
    for index, agent in enumerate(agents):
        config = _agent_config(args.agent_config)
        bench = run_benchmark(
            tasks, agent, config, runs=args.runs, out_dir=Path(args.out) if args.out else None
        )
        overall = bench.summary.get("overall", {})
        # Agents may be named twice (a self-comparison sanity check), so key the
        # outcome vectors by position rather than by name.
        key = f"{index}:{agent}"
        outcomes[key] = [bool(r.success) for r in bench.results]
        variance_rows.extend(
            {"agent": agent, "task_id": r.task_id, "success": bool(r.success)}
            for r in bench.results
        )
        standings.append(
            {
                "agent": agent,
                "key": key,
                "success_rate": overall.get("rate"),
                "ci": [overall.get("ci_low"), overall.get("ci_high")],
                "n": overall.get("n"),
                "steps_mean": overall.get("steps_mean"),
                "failed_tool_calls_mean": overall.get("failed_tool_calls_mean"),
                "wall_ms_p95": overall.get("wall_ms_p95"),
                "flakiness": overall.get("flakiness"),
            }
        )

    standings.sort(key=lambda row: _as_rate(row.get("success_rate")), reverse=True)

    verdict = "ranked"
    note = "single agent; nothing to compare"
    if len(standings) >= 2:
        leader, runner_up = standings[0], standings[1]
        leader_vec = outcomes[str(leader["key"])]
        runner_vec = outcomes[str(runner_up["key"])]
        note = significance_note(len(leader_vec), len(runner_vec))
        for challenger in standings[1:]:
            challenger_vec = outcomes[str(challenger["key"])]
            challenger["paired_vs_leader"] = paired_delta(leader_vec, challenger_vec)
            challenger["effect_size_h"] = effect_size_cohens_h(
                _as_rate(leader.get("success_rate")), _as_rate(challenger.get("success_rate"))
            )
        enough = note.startswith("sample sizes sufficient")
        separated = _intervals_are_disjoint(leader.get("ci"), runner_up.get("ci"))
        if not (enough and separated):
            verdict = "not distinguishable at this sample size"

    # Two additions that answer questions the frequentist verdict cannot.
    #
    # `power` says what this sweep was capable of detecting, which is what makes
    # "not distinguishable" readable: without it, that verdict is indistinguish-
    # able from "these agents are the same", and they are opposite claims.
    #
    # `bayesian` reports P(leader is better) directly. People read a confidence
    # interval as though it said that anyway; saying it outright is more honest
    # than letting the misreading do the work.
    from tooltrace.analysis.power import bayesian_comparison, power_report, variance_decomposition

    smallest_arm = min((len(v) for v in outcomes.values()), default=0)
    payload_extras: dict[str, object] = {
        "power": power_report(
            smallest_arm,
            baseline_rate=_as_rate(standings[0].get("success_rate")) if standings else 0.5,
        ),
    }
    if len(standings) >= 2:
        leader_vec = outcomes[str(standings[0]["key"])]
        runner_vec = outcomes[str(standings[1]["key"])]
        payload_extras["bayesian"] = bayesian_comparison(
            sum(leader_vec),
            len(leader_vec),
            sum(runner_vec),
            len(runner_vec),
            label_a=str(standings[0]["agent"]),
            label_b=str(standings[1]["agent"]),
        )
    # Split the wobble: repeating one agent on one task and getting different
    # answers is nondeterminism; differing across tasks is the benchmark working.
    # A single standard deviation conflates them, which is how a stable agent on
    # a diverse task set gets described as flaky.
    payload_extras["variance"] = variance_decomposition(variance_rows)

    for row in standings:
        row.pop("key", None)
    payload = {
        "standings": standings,
        "verdict": verdict,
        "note": note,
        "ranking_is_provisional": verdict != "ranked",
        "selection": selection,
        **payload_extras,
    }
    _emit(payload, args.json)
    return EXIT_OK


def _as_rate(value: object) -> float:
    """A success rate as a float, treating an unmeasured rate as 0.0 for ordering only."""
    return float(value) if isinstance(value, int | float) else 0.0


def _intervals_are_disjoint(a: object, b: object) -> bool:
    """True when two [low, high] intervals do not overlap.

    A missing bound means we cannot show separation, so the answer is False --
    absence of evidence is never reported as separation.
    """
    if not (isinstance(a, list) and isinstance(b, list) and len(a) == 2 and len(b) == 2):
        return False
    if any(x is None for x in (*a, *b)):
        return False
    a_low, a_high = float(a[0]), float(a[1])
    b_low, b_high = float(b[0]), float(b[1])
    return a_low > b_high or b_low > a_high


def cmd_compare(args: argparse.Namespace) -> int:
    from tooltrace.analysis.compare import compare_bundles

    try:
        comps = compare_bundles(
            Path(args.baseline),
            Path(args.current),
            metrics=args.metrics.split(",") if args.metrics else None,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    _emit([c.model_dump() for c in comps], args.json)
    return EXIT_OK


def cmd_baseline(args: argparse.Namespace) -> int:
    """Record a bundle as the named baseline."""
    registry_path = Path(".tooltrace-baselines.json")
    registry: dict[str, str] = {}
    if registry_path.is_file():
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry[args.name] = str(Path(args.bundle).resolve())
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    _emit({"baseline": args.name, "bundle": registry[args.name]}, args.json)
    return EXIT_OK


def cmd_regression(args: argparse.Namespace) -> int:
    from tooltrace.analysis.compare import check_regression

    # Parsed inside the guarded block: --thresholds takes inline JSON, and a
    # path or a typo previously escaped as a raw JSONDecodeError traceback.
    try:
        thresholds = json.loads(args.thresholds)
    except json.JSONDecodeError as exc:
        print(
            f"error: --thresholds expects inline JSON, not a file path: {exc}",
            file=sys.stderr,
        )
        print(
            'hint: --thresholds takes inline JSON, e.g. {"score":{"min_delta":-0.05}}',
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        report = check_regression(Path(args.baseline), Path(args.current), thresholds)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    _emit(report.model_dump(), args.json)
    if not report.passed:
        print("REGRESSION DETECTED", file=sys.stderr)
    return report.exit_code


def cmd_validate(args: argparse.Namespace) -> int:
    from tooltrace.tasks.sdk import validate_task_dir

    path = Path(args.path)
    tasks, errors = validate_task_dir(path)
    payload = {"valid": len(tasks), "errors": errors}
    _emit(payload, args.json)
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    return EXIT_OK if not errors else EXIT_TASK


def cmd_reproduce(args: argparse.Namespace) -> int:
    from tooltrace.artifacts.bundles_repro import reproduce_bundle

    report = reproduce_bundle(
        Path(args.bundle),
        out_dir=Path(args.out) if args.out else None,
        rerun=not args.no_rerun,
    )
    _emit(report.__dict__, args.json)
    return (
        EXIT_OK
        if report.verified and (not report.rerun_attempted or report.rerun_success)
        else EXIT_RUN
    )


def cmd_verify(args: argparse.Namespace) -> int:
    """Check a bundle's checksums and its conformance to the published schemas.

    The capability existed but had no name a user would look for: verification
    lived under `reproduce --no-rerun`, a command documented as "verify and
    re-run", so the cheap read-only check was reachable only by asking the
    expensive one not to do its main job. Third-party auditing is the whole
    point of a checksummed bundle, so it gets a verb.

    Two independent checks, reported separately because they fail for different
    reasons: checksums catch a file that changed after it was written; schema
    validation catches a bundle that never matched the published format.
    """
    from tooltrace.analysis.integrity import check_bundle_integrity, installed_task_for
    from tooltrace.artifacts.bundles import load_bundle_result, read_manifest, verify_bundle
    from tooltrace.artifacts.validation import validate_bundle_artifacts

    bundle = Path(args.bundle)
    try:
        checksum_problems = verify_bundle(bundle)
    except BundleError as exc:
        _emit({"bundle": str(bundle), "ok": False, "problems": [str(exc)]}, args.json)
        return EXIT_RUN

    schema_problems = [] if args.no_schema else validate_bundle_artifacts(bundle)

    # A signature is optional and separate from the checksums: checksums are
    # tamper-*evident* (they detect a change) while a signature establishes who
    # produced the bundle. `verify_bundle_signature` shipped with no caller
    # outside the test suite, so the distinction the docs draw was unreachable.
    signature: dict[str, object] = {"checked": False}
    if args.signature:
        from tooltrace.analysis.core import verify_bundle_signature

        signature = {"checked": True, **verify_bundle_signature(bundle, Path(args.signature))}

    integrity: dict[str, object] = {"ok": True, "problems": [], "skipped": True}
    if not args.no_integrity:
        installed = None
        with contextlib.suppress(Exception):
            installed = installed_task_for(load_bundle_result(bundle).task_id)
        integrity = check_bundle_integrity(bundle, installed)
    raw_problems = integrity.get("problems")
    integrity_problems = list(raw_problems) if isinstance(raw_problems, list) else []

    manifest: dict[str, object] = {}
    with contextlib.suppress(BundleError, ValueError):
        manifest = read_manifest(bundle)

    payload = {
        "bundle": str(bundle),
        "ok": (
            not checksum_problems
            and not schema_problems
            and not integrity_problems
            # An unverifiable signature the caller explicitly asked about is a
            # failure. Not asking is not a failure.
            and (not signature.get("checked") or bool(signature.get("verified")))
        ),
        "checksums_ok": not checksum_problems,
        "schema_ok": not schema_problems,
        "integrity_ok": not integrity_problems,
        "checksum_problems": checksum_problems,
        "schema_problems": schema_problems,
        "integrity": integrity,
        "signature": signature,
        "framework_version": manifest.get("framework_version"),
        "compatibility_key": manifest.get("compatibility_key"),
        "trust_state": manifest.get("trust_state"),
    }
    _emit(payload, args.json)
    return EXIT_OK if payload["ok"] else EXIT_RUN


def cmd_report(args: argparse.Namespace) -> int:
    from tooltrace.reports import export_report

    results = []
    for pattern_dir in [Path(p) for p in args.bundles]:
        for bundle in sorted(pattern_dir.rglob("*.tooltrace")):
            from tooltrace.artifacts.bundles import load_bundle_result

            row = load_bundle_result(bundle).model_dump(mode="json")
            # attach trace timeline + workspace diff so HTML/MD reports can embed them
            trace_path = bundle / "trace.jsonl"
            diff_path = bundle / "workspace.diff"
            if trace_path.is_file():
                events = []
                for line in trace_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        try:
                            ev = json.loads(line)
                            events.append(
                                f"#{ev.get('seq')} {ev.get('type')}"
                                f"{': ' + str(ev.get('payload', {}).get('tool')) if ev.get('payload', {}).get('tool') else ''}"
                                f"{': ' + str(ev.get('payload', {}).get('status')) if ev.get('payload', {}).get('status') else ''}"
                            )
                        except json.JSONDecodeError:
                            continue
                row["trace_timeline"] = events
            if diff_path.is_file():
                row["workspace_diff"] = diff_path.read_text(encoding="utf-8")[:20000]
            results.append(row)
    payload = {"results": results}
    text = export_report(payload, args.format, Path(args.output) if args.output else None)
    if not args.output:
        print(text)
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    from tooltrace.reports import export_with_plugins

    payload = json.loads(sys.stdin.read()) if args.stdin else {"results": []}
    produced = export_with_plugins(payload, Path(args.out))
    _emit({"produced": produced}, args.json)
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    """Serve web/dist statically for local preview of the frontend."""
    import functools
    import http.server
    import socketserver

    dist = Path(args.dir)
    if not dist.is_dir():
        print(
            f"error: {dist} not found; build the frontend first (cd web && npm run build)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    with socketserver.TCPServer((args.host, args.port), handler) as httpd:
        print(f"serving {dist} at http://{args.host}:{args.port} (Ctrl+C to stop)")
        with contextlib.suppress(KeyboardInterrupt):
            httpd.serve_forever()
    return EXIT_OK


def cmd_lint(args: argparse.Namespace) -> int:
    """Task-lint: ambiguous scoring, unreachable assertions, unsafe network,
    non-deterministic fixtures."""
    from tooltrace.tasks import load_all_tasks
    from tooltrace.tasks.linting import lint_pack

    tasks = load_all_tasks()
    if args.path:
        from tooltrace.tasks.sdk import validate_task_dir

        tasks, _ = validate_task_dir(Path(args.path))
    report = lint_pack(tasks)
    total = sum(len(v) for v in report.values())
    payload = {
        "tasks": len(report),
        "issues": total,
        "detail": {
            k: [i.model_dump() if hasattr(i, "model_dump") else str(i) for i in v]
            for k, v in report.items()
        },
    }
    _emit(payload, args.json)
    return EXIT_OK if total == 0 else EXIT_TASK


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Validate fixtures/assertions/sandbox lifecycle without invoking a model."""
    from tooltrace.tasks import find_task
    from tooltrace.tasks.linting import dry_run_task

    try:
        task = find_task(args.task)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_TASK
    report = dry_run_task(task)
    data = (
        report.model_dump(mode="json") if hasattr(report, "model_dump") else {"report": str(report)}
    )
    _emit(data, args.json)
    ok = bool(data.get("ok", True)) if isinstance(data, dict) else True
    return EXIT_OK if ok else EXIT_TASK


PERTURBATION_KINDS = (
    "tool_failure",
    "command_exit",
    "moved_file",
    "api_error",
    "delay",
    "ambiguous_error",
    "irrelevant_files",
)


def cmd_perturb(args: argparse.Namespace) -> int:
    """Run a task with injected faults and quantify recovery (§4)."""
    from tooltrace.core.models import PerturbationSpec
    from tooltrace.runners.runner import TaskRunner
    from tooltrace.tasks import find_task

    try:
        task = find_task(args.task)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_TASK

    specs = list(task.perturbations)
    if args.perturbation:
        kind, _, tool = args.perturbation.partition(":")
        if kind not in PERTURBATION_KINDS:
            print(
                f"error: unknown perturbation kind {kind!r}; choose from "
                f"{', '.join(PERTURBATION_KINDS)} (optionally 'kind:tool')",
                file=sys.stderr,
            )
            return EXIT_USAGE
        params: dict[str, object] = {"tool": tool} if tool else {}
        specs = [*specs, PerturbationSpec(kind=kind, params=params)]
    if not specs:
        print(
            "error: task declares no perturbations; pass --perturbation kind[:tool]",
            file=sys.stderr,
        )
        return EXIT_TASK

    if args.runs < 1:
        print("error: --runs must be >= 1", file=sys.stderr)
        return EXIT_USAGE

    # Fresh runner per run: the engine is per-run state; extra CLI-requested
    # faults are folded into a copy of the task so the runner path is unchanged.
    effective_task = task.model_copy(update={"perturbations": specs})
    agent_config: dict[str, object] | None = None
    if args.agent == "scripted":
        script = task.metadata.get("scripted_script")
        if isinstance(script, list):
            agent_config = {"script": script}
    runner = TaskRunner(output_dir=Path(args.out) if args.out else None)
    runs: list[dict[str, Any]] = []
    for _ in range(args.runs):
        result, events, diff_text = runner.run(effective_task, args.agent, agent_config)
        failed_calls = result.failed_tool_calls
        recovered = bool(result.success and failed_calls > 0) or (result.success and bool(specs))
        runs.append(
            {
                "success": bool(result.success),
                "score": float(result.score.total),
                "failed_tool_calls": int(failed_calls),
                "recovered": recovered,
                "wall_ms": float(result.wall_ms),
                "bundle": getattr(result, "bundle_name", None),
            }
        )
        if args.out:
            details = {}
            for e in events:
                if e.type == "validation" and isinstance(e.payload.get("details"), dict):
                    details = {str(k): str(v) for k, v in e.payload["details"].items()}
                    break
            from tooltrace.artifacts.bundles import write_bundle

            bundle = write_bundle(
                Path(args.out), result, events, task, diff_text, details, agent_config=agent_config
            )
            runs[-1]["bundle"] = bundle.name

    successes = sum(1 for r in runs if r["recovered"])
    recovery_rate = successes / len(runs)
    # `environment_note()` states that api_error faults are injected at the
    # tool layer and generate no real traffic. It existed with no caller, so a
    # reader of "injected api_error" could reasonably have believed a network
    # fault was simulated. It travels with the result now.
    from tooltrace.perturbations import environment_note

    payload = {
        "task": task.id,
        "agent": args.agent,
        "environment_note": environment_note(),
        "perturbations": [
            {"kind": s.kind, **({"tool": s.params["tool"]} if "tool" in s.params else {})}
            for s in specs
        ],
        "runs": len(runs),
        "recovered_runs": successes,
        "recovery_rate": recovery_rate,
        "failed_tool_calls_total": sum(r["failed_tool_calls"] for r in runs),
        "results": runs if not args.summary else None,
    }
    if args.summary:
        payload.pop("results")
    _emit(payload, args.json)
    return EXIT_OK if recovery_rate >= args.min_recovery_rate else EXIT_RUN


def cmd_trace(args: argparse.Namespace) -> int:
    """Inspect a .tooltrace bundle's trace without leaving the terminal."""
    from tooltrace.artifacts.bundles import (
        load_bundle_result,
        load_bundle_trace,
        verify_bundle,
    )

    bundle_dir = Path(args.bundle)
    if not bundle_dir.is_dir():
        print(f"error: bundle directory not found: {bundle_dir}", file=sys.stderr)
        return EXIT_USAGE
    problems = verify_bundle(bundle_dir)
    if problems:
        print(f"error: bundle integrity check failed: {'; '.join(problems)}", file=sys.stderr)
        return EXIT_RUN
    result = load_bundle_result(bundle_dir)

    if args.assertions:
        events = [e for e in load_bundle_trace(bundle_dir) if e.type == "validation"]
    else:
        events = load_bundle_trace(bundle_dir)
    if args.filter:
        needle = args.filter.lower()
        events = [e for e in events if needle in json.dumps(e.model_dump(mode="json")).lower()]

    rows = [
        {
            "seq": e.seq,
            "type": str(e.type),
            **({k: str(e.payload[k]) for k in ("tool", "status", "duration_ms") if k in e.payload}),
        }
        for e in events[: max(0, args.limit)]
    ]
    payload = {
        "bundle": bundle_dir.name,
        "task": result.task_id,
        "run_id": result.run_id,
        "success": result.success,
        "checksums_ok": True,
        "events_shown": len(rows),
        "events_total": len(events),
        "events": rows,
    }
    if args.json:
        _emit(payload, True)
    else:
        print(f"bundle   : {payload['bundle']}")
        print(
            f"task     : {payload['task']}  (run {payload['run_id']}, "
            f"{'PASS' if result.success else 'FAIL'})"
        )
        print(f"events   : {len(rows)} of {len(events)} shown")
        for r in rows:
            extras = " ".join(f"{k}={v}" for k, v in r.items() if k not in {"seq", "type"})
            print(f"  #{r['seq']:<4} {r['type']:<14} {extras}")
    return EXIT_OK


def cmd_self_test(args: argparse.Namespace) -> int:
    """Harness self-test: sandbox cleanup, scoring determinism, timers,
    fixture integrity, trace integrity - no model required."""
    from tooltrace.sandbox.infra import harness_self_test

    def sandbox_factory() -> object:
        from tooltrace.sandbox.infra import WindowsNativeSandbox

        return WindowsNativeSandbox()

    def scorer(value: str) -> float:
        return float(len(value))

    try:
        report = harness_self_test(sandbox_factory, scorer)
    except Exception as exc:
        print(f"error: self-test could not construct a local sandbox: {exc}", file=sys.stderr)
        return EXIT_RUN
    _emit(report, args.json)
    return EXIT_OK if report["ok"] else EXIT_RUN


def cmd_snapshot(args: argparse.Namespace) -> int:
    """Generate or verify a reproducible dataset snapshot with hashes."""
    from tooltrace.analysis import generate_snapshot, verify_snapshot

    out = Path(args.output)
    if args.verify:
        problems = verify_snapshot(out, Path(args.source))
        _emit({"verified": not problems, "problems": problems}, args.json)
        return EXIT_OK if not problems else EXIT_TASK
    snap = generate_snapshot(Path(args.source), out, args.changelog)
    _emit({"snapshot_sha256": snap["snapshot_sha256"], "file_count": snap["file_count"]}, args.json)
    return EXIT_OK


def cmd_ingest(args: argparse.Namespace) -> int:
    """Convert external traces (OTel GenAI spans / OpenAI steps) into a
    ToolTrace trace event stream, classify it and optionally write JSONL."""
    from tooltrace.analysis.failures import classify
    from tooltrace.ingest import format_counts, from_openai_steps, from_otel_spans

    src = Path(args.infile)
    if not src.is_file():
        print(f"input file not found: {src}", file=sys.stderr)
        return EXIT_USAGE
    try:
        data: Any = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Fall back to JSONL (one record per line) — the common export format.
        data = []
        try:
            for line in src.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    data.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"invalid input JSON/JSONL: {exc}", file=sys.stderr)
            return EXIT_USAGE

    records = (
        data.get("spans" if args.format == "otel-spans" else "steps")
        if isinstance(data, dict)
        else data
    )
    if not isinstance(records, list):
        expected = '"spans"' if args.format == "otel-spans" else '"steps"'
        print(f"input must be a list or an object with key {expected}", file=sys.stderr)
        return EXIT_USAGE

    if args.format == "otel-spans":
        events = from_otel_spans(records, task_id=args.task_id, agent=args.agent)
        agent_name = args.agent or "unknown"
    else:
        agent_name = args.agent or "openai-compat"
        events = from_openai_steps(records, task_id=args.task_id, agent=agent_name)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(e.model_dump_json() for e in events) + "\n", encoding="utf-8")

    reason = classify(events)
    summary_reason = getattr(reason, "reason", reason)  # Classification → FailureReason
    payload: dict[str, object] = {
        "task_id": args.task_id,
        "format": args.format,
        "agent": agent_name,
        "events": len(events),
        "counts": format_counts(events),
        "failure_rule": str(getattr(reason, "rule", "")),
        "failure_reason": str(getattr(summary_reason, "value", summary_reason)),
        "out": str(args.out) if args.out else None,
    }

    if args.score_against:
        from tooltrace.scoring.composite import score_trace_only
        from tooltrace.scoring.trace_view import TraceView
        from tooltrace.tasks import load_all_tasks

        task = next((t for t in load_all_tasks() if t.id == args.score_against), None)
        if task is None:
            print(f"error: unknown task {args.score_against!r}", file=sys.stderr)
            return EXIT_TASK

        score, details, skipped = score_trace_only(task, TraceView.from_events(events))
        payload["scored_against"] = task.id
        payload["score"] = score.model_dump(mode="json")
        payload["score_details"] = details
        # A production trace has no workspace, so every `(params, workspace)`
        # assertion is unanswerable. Naming them is the whole point: a partial
        # score presented as a complete one would be the worst output here.
        payload["skipped_assertions"] = skipped
        payload["is_partial_score"] = bool(skipped)
        if not score.components:
            print(
                f"note: {task.id} declares no trajectory assertions, so an ingested "
                "trace cannot be scored against it",
                file=sys.stderr,
            )
        elif skipped:
            print(
                f"note: scored {len(score.components)} of "
                f"{len(score.components) + len(skipped)} assertions; "
                f"{len(skipped)} need a workspace an ingested trace does not have",
                file=sys.stderr,
            )

    _emit(payload, args.json)
    return EXIT_OK


def cmd_evidence(args: argparse.Namespace) -> int:
    """Assemble an evidence dossier from bundles for a regulated review.

    This produces *inputs* to a compliance determination and never makes one.
    Whether a system meets its legal obligations is an organisational judgement
    about that system in its deployment context, made by people accountable for
    it. Emitting a "compliant" verdict from a benchmark run would be actively
    misleading in a domain carrying eight-figure penalties, and the fact that a
    machine produced it would lend it unearned authority.
    """
    from tooltrace.analysis.evidence import build_dossier, render_markdown, verify_chain
    from tooltrace.runners.runner import _now_iso

    bundles: list[Path] = []
    for pattern in args.bundles:
        path = Path(pattern)
        bundles.extend(sorted(path.glob("*.tooltrace")) if path.is_dir() else [path])
    bundles = [b for b in bundles if b.is_dir()]
    if not bundles:
        print("error: no .tooltrace bundles found", file=sys.stderr)
        return EXIT_USAGE

    try:
        dossier = build_dossier(bundles, generated_at=_now_iso())
    except BundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_RUN

    problems = verify_chain(dossier)
    if problems:
        print(f"error: the dossier's own hash chain does not verify: {problems}", file=sys.stderr)
        return EXIT_RUN

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "evidence.json").write_text(json.dumps(dossier, indent=2), encoding="utf-8")
        (out / "evidence.md").write_text(render_markdown(dossier), encoding="utf-8")

    unverified = [r["bundle"] for r in dossier["runs"] if not r["verified"]]
    if unverified:
        print(
            f"warning: {len(unverified)} bundle(s) failed checksum verification and are "
            "recorded as unverified in the dossier",
            file=sys.stderr,
        )

    _emit(
        {
            "generated_at": dossier["generated_at"],
            "runs": len(dossier["runs"]),
            "unverified": unverified,
            "chain_head": dossier["chain_head"],
            "obligations": [
                {
                    "article": o["article"],
                    "evidence": len(o["evidence"]),
                    "gaps": len(o["gaps"]),
                }
                for o in dossier["obligations"]
            ],
            "out": str(args.out) if args.out else None,
            "is_compliance_determination": False,
        },
        args.json,
    )
    return EXIT_OK


def cmd_mcp_conformance(args: argparse.Namespace) -> int:
    """Check an MCP server against the protocol, over stdio or HTTP.

    MCP has effectively won the agent-to-tool layer, which makes "does this
    server behave correctly" a question many people now have. Exit is non-zero
    only on a *required* failure: a missing tool description is a real
    usability problem and not a protocol violation, and conflating them would
    make this an opinion rather than a measurement.

    `--url` reaches a hosted server. The checks do not change with the
    transport, which is the point of being able to run them over each: the
    protocol is the same, so a difference in the results is a difference in the
    server rather than in the question.
    """
    from tooltrace.agents.mcp import fake_server_command
    from tooltrace.agents.mcp_conformance import report

    if args.url:
        result = report(url=args.url)
    else:
        command = list(args.command) if args.command else fake_server_command()
        result = report(command)

    if not args.json:
        for check in result["checks"]:
            mark = "pass" if check["passed"] else "FAIL"
            print(f"  [{mark:>4}] {check['severity']:<11} {check['name']}: {check['detail']}")
    _emit(result, args.json)

    if result["required_failures"]:
        print(
            f"required conformance failures: {result['required_failures']}",
            file=sys.stderr,
        )
        return EXIT_RUN
    if result["recommended_failures"]:
        print(
            f"note: server works, but misses recommended behaviour: "
            f"{result['recommended_failures']}",
            file=sys.stderr,
        )
    return EXIT_OK


def cmd_server(args: argparse.Namespace) -> int:
    """Run the self-hosted team/enterprise API server."""
    from tooltrace.server.core import serve

    httpd = serve(host=args.host, port=args.port)
    print(f"tooltrace server listening on http://{args.host}:{args.port} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        httpd.shutdown()
    return EXIT_OK


def cmd_task_group(args: argparse.Namespace) -> int:
    from tooltrace.tasks.sdk import scaffold_task, test_pack, validate_task_dir

    if args.task_cmd == "scaffold":
        target = scaffold_task(Path(args.pack_dir), args.task_id)
        _emit({"created": str(target)}, args.json)
        return EXIT_OK
    if args.task_cmd == "validate":
        tasks, errors = validate_task_dir(Path(args.path))
        _emit({"valid": len(tasks), "errors": errors}, args.json)
        return EXIT_OK if not errors else EXIT_TASK
    if args.task_cmd == "test":
        passed, problems = test_pack(Path(args.path))
        _emit({"passed": passed, "problems": problems}, args.json)
        return EXIT_OK if not problems else EXIT_TASK
    return EXIT_USAGE


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    from tooltrace.cli.init import CHOICES as ADAPTERS_FOR_INIT

    p = argparse.ArgumentParser(prog="tooltrace", description=__doc__)
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="command")

    def add(name: str, fn: CommandHandler, help_: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(func=fn)
        sp.add_argument("--json", action="store_true", help="structured JSON output")
        return sp

    add("doctor", cmd_doctor, "environment and registry health check")

    i = add("init", cmd_init, "set up this project against your own agent and run one task")
    i.add_argument(
        "--dir", default=".", help="where to write the config and workflow (default: here)"
    )
    i.add_argument(
        "--agent",
        choices=sorted(ADAPTERS_FOR_INIT),
        help="adapter for your agent; prompted when interactive, else subprocess",
    )
    i.add_argument("--command", help="subprocess: how to invoke your agent, with {objective}")
    i.add_argument("--base-url", help="openai_compat: endpoint, e.g. http://localhost:11434/v1")
    i.add_argument("--model", help="openai_compat: model name")
    i.add_argument(
        "--api-key-env",
        help="openai_compat: NAME of the env var holding the key. Never the key itself.",
    )
    i.add_argument("--task", help="task to run first (default: a short offline one)")
    i.add_argument("--no-ci", action="store_true", help="do not write any CI configuration")
    i.add_argument(
        "--ci",
        default="github",
        choices=["github", "gitlab", "jenkins", "circleci"],
        help="which CI system to write configuration for (default: github)",
    )
    i.add_argument("--no-run", action="store_true", help="write the files without running a task")
    i.add_argument("--force", action="store_true", help="overwrite existing files")

    bd = add("badge", cmd_badge, "render an embeddable reliability badge (SVG)")
    bd.add_argument("--summary", help="a `benchmark --summary --json` payload")
    bd.add_argument("--bundles", help="a directory of .tooltrace bundles")
    bd.add_argument("--out", help="write the SVG here (and the shields endpoint beside it)")
    bd.add_argument("--svg-url", help="URL the README should point at, for the embed snippet")
    bd.add_argument("--link", help="URL the badge should link to")

    pr = add("pr-report", cmd_pr_report, "compare two sets of runs for a pull request")
    pr.add_argument("--baseline", required=True, help="directory of baseline bundles")
    pr.add_argument("--current", required=True, help="directory of this branch's bundles")
    pr.add_argument("--out", help="write the markdown comment here")
    pr.add_argument(
        "--metrics",
        help=(
            "comma-separated metrics to gate on (default: all). On a shared CI runner, "
            "`success_rate,score,steps,failed_tool_calls` excludes wall-clock"
        ),
    )

    pw = add("power", cmd_power, "what a planned sweep can detect, before you run it")
    pw.add_argument("--runs", type=int, default=30, help="runs per arm you intend to do")
    pw.add_argument(
        "--detect",
        type=float,
        help="instead, ask how many runs a difference this large needs (e.g. 0.10)",
    )
    pw.add_argument(
        "--baseline-rate",
        type=float,
        default=0.5,
        help="expected success rate; 0.5 is the worst case and the default",
    )

    ct = add("cost", cmd_cost, "where the money went, and what the next sweep would cost")
    ct.add_argument("--bundles", default="results", help="directory of .tooltrace bundles")
    ct.add_argument("--forecast-tasks", type=int, help="tasks in a planned sweep")
    ct.add_argument("--forecast-runs", type=int, help="runs per task in a planned sweep")
    ct.add_argument(
        "--human-baseline",
        type=float,
        help=(
            "cost per task if a person did it. No default: a viability verdict against "
            "an invented baseline is an opinion, not a measurement"
        ),
    )

    ow = add("owasp", cmd_owasp, "OWASP Agentic Top 10 coverage, from packs that run here")
    ow.add_argument("--markdown", action="store_true", help="emit the docs table")

    at = add("attest", cmd_attest, "reproduce a bundle and record who did it")
    at.add_argument("bundle")
    at.add_argument(
        "--attester", help="who is attesting. Omit to read the bundle's existing attestations"
    )
    at.add_argument("--at", help="ISO timestamp; defaults to now")
    at.add_argument("--signature", help="cosign signature over this attestation, if you have one")
    at.add_argument(
        "--promote",
        action="store_true",
        help="write the supported trust state into the bundle. Never awards MAINTAINER_VERIFIED",
    )

    cd = add("card", cmd_card, "generate a system card for an agent from its runs")
    cd.add_argument("--bundles", default="results")
    cd.add_argument("--agent", help="required when the bundles cover several agents")
    cd.add_argument("--at", help="ISO timestamp for the card; defaults to the newest run")
    cd.add_argument("--out", help="write the markdown card here")

    sa = add("self-audit", cmd_self_audit, "would the evidence you hold demonstrate anything?")
    sa.add_argument("--bundles", default="results")

    dr = add("drift", cmd_drift, "has behaviour moved between two windows of runs?")
    dr.add_argument("--current", default="results", help="the recent window")
    dr.add_argument("--baseline", help="the window to compare against")
    dr.add_argument(
        "--objective",
        type=float,
        help="reliability SLO (0..1); reports the error budget left in --current",
    )

    pt = add("promote-trace", cmd_promote_trace, "turn a production trace into a draft task")
    pt.add_argument("trace", help="a JSONL trace, e.g. from `tooltrace ingest --out`")
    pt.add_argument("--task-id", required=True)
    pt.add_argument("--objective", help="what the agent should have done")
    pt.add_argument("--incident", help="an incident reference to record in the task")
    pt.add_argument("--out", help="write the draft task YAML here")

    add("backends", cmd_backends, "local model servers, and which are listening")

    mf = add("mcp-fuzz", cmd_mcp_fuzz, "send malformed JSON-RPC at an MCP server")
    mf.add_argument("--markdown", action="store_true", help="emit a table for a bug report")
    mf.add_argument(
        "command",
        nargs="*",
        help="the server command. Use `--` first if it takes flags. Defaults to the fixture",
    )

    ac = add("a2a-card", cmd_a2a_card, "check an A2A Agent Card and its signature")
    ac.add_argument("card", help="path to an agent-card.json")
    ac.add_argument(
        "--key",
        action="append",
        help="verification key as KID=SECRET, supplied by you and never read from the card",
    )

    ms = add("mcp-scan", cmd_mcp_scan, "score many MCP servers at once")
    source = ms.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--from",
        dest="from_file",
        help="a JSON file of servers you wrote. Only this source may name a command to run",
    )
    source.add_argument(
        "--registry",
        help="fetch a server list over HTTP. URL targets only -- a command from a registry "
        "is not executed",
    )
    ms.add_argument("--markdown", action="store_true", help="emit a table")

    mv = add("mcp-versions", cmd_mcp_versions, "which MCP revisions a server implements")
    mv.add_argument("--markdown", action="store_true", help="emit a table for a bug report")
    mv.add_argument("--url", help="reach a hosted server over HTTP instead of stdio")
    mv.add_argument(
        "command",
        nargs="*",
        help="the server command. Use `--` first if it takes flags. Defaults to the fixture",
    )

    add("agents", cmd_agents, "list registered agent adapters")

    tl = add("tools", cmd_tools, "what a model is told about the tools it may call")
    tl.add_argument(
        "--dialect",
        choices=["openai", "anthropic", "mcp", "gemini", "prompt"],
        help="render the catalogue as one provider receives it",
    )
    tl.add_argument(
        "--equivalence",
        action="store_true",
        help="does one declaration mean the same thing to every provider?",
    )

    t = add("tasks", cmd_tasks, "list available tasks")
    t.add_argument("--category")

    r = add("run", cmd_run, "run one agent on one task")
    r.add_argument("--task", required=True)
    r.add_argument("--agent", default="scripted")
    r.add_argument("--agent-config")
    r.add_argument("--out")

    b = add("benchmark", cmd_benchmark, "run repeated benchmarks")
    b.add_argument("--agent", default="scripted")
    b.add_argument("--agent-config")
    b.add_argument("--runs", type=int, default=1)
    b.add_argument("--task", help="comma-separated task ids (default: all)")
    b.add_argument("--out")
    b.add_argument("--summary", action="store_true")
    b.add_argument(
        "--budget",
        type=float,
        help=(
            "hard spending ceiling for this sweep. The sweep stops rather than "
            "continuing, and the summary reports what did not run"
        ),
    )
    b.add_argument("--budget-currency", default="USD")
    b.add_argument("--min-success-rate", type=float, default=0.0)
    b.add_argument(
        "--context-sweep",
        action="store_true",
        help="run the long-context scale family and report metrics per context size",
    )

    s = add("showdown", cmd_showdown, "benchmark several agents and rank them")
    s.add_argument("--agents", required=True, help="comma-separated agent names")
    s.add_argument("--task")
    s.add_argument("--runs", type=int, default=1)
    s.add_argument("--agent-config")
    s.add_argument("--out")

    # Nobody runs a full benchmark on every pull request, so a cheap, *recorded*
    # subset is what makes CI integration happen at all.
    for _sub in (b, s):
        _sub.add_argument(
            "--limit",
            type=int,
            help="run at most N tasks; the selection is recorded, not silently cut",
        )
        _sub.add_argument(
            "--shuffle",
            action="store_true",
            help="shuffle before --limit so a subset is not always the same N tasks",
        )
        _sub.add_argument("--seed", type=int, help="seed for --shuffle (default 0)")

    c = add("compare", cmd_compare, "compare two bundles metric-by-metric")
    c.add_argument("--baseline", required=True)
    c.add_argument("--current", required=True)
    c.add_argument("--metrics")

    bl = add("baseline", cmd_baseline, "record a bundle as a named baseline")
    bl.add_argument("--name", required=True)
    bl.add_argument("--bundle", required=True)

    rg = add("regression", cmd_regression, "check current bundle against baseline thresholds")
    rg.add_argument("--baseline", required=True)
    rg.add_argument("--current", required=True)
    rg.add_argument("--thresholds", required=True, help='JSON e.g. {"score":{"min_delta":-0.05}}')

    v = add("validate", cmd_validate, "validate task files against the schema")
    v.add_argument("--path", required=True)

    rp = add("reproduce", cmd_reproduce, "verify and re-run a .tooltrace bundle")
    rp.add_argument("bundle")
    rp.add_argument("--out")
    rp.add_argument("--no-rerun", action="store_true")
    v = add("verify", cmd_verify, "verify a bundle's checksums and schema conformance")
    v.add_argument("bundle")
    v.add_argument(
        "--no-schema", action="store_true", help="check checksums only, skip schema validation"
    )
    v.add_argument(
        "--signature",
        help=(
            "cosign signature file to verify against. Checksums are tamper-evident; "
            "a signature establishes who produced the bundle"
        ),
    )
    v.add_argument(
        "--no-integrity",
        action="store_true",
        help="skip the anti-gaming checks (skipped assertions, modified task, leaked answers)",
    )

    rep = add("report", cmd_report, "aggregate bundles into a report")
    rep.add_argument("--bundles", nargs="+", required=True)
    rep.add_argument("--format", default="markdown", choices=["json", "csv", "md", "junit", "html"])
    rep.add_argument("--output")

    ex = add("export", cmd_export, "run exporter plugins on a JSON payload")
    ex.add_argument("--out", required=True)
    ex.add_argument("--stdin", action="store_true")

    sv = add("serve", cmd_serve, "serve built frontend locally")
    sv.add_argument("--dir", default="web/dist")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)

    tk = sub.add_parser("task", help="task authoring SDK")
    tksub = tk.add_subparsers(dest="task_cmd", required=True)
    sc = tksub.add_parser("scaffold")
    sc.add_argument("--pack-dir", required=True)
    sc.add_argument("--task-id", required=True)
    va = tksub.add_parser("validate")
    va.add_argument("--path", required=True)
    te = tksub.add_parser("test")
    te.add_argument("--path", required=True)
    # cmd_task_group emits through _emit(..., args.json) for all three, so each
    # needs the flag. Without it `task scaffold` wrote the file and *then* died
    # with AttributeError: 'Namespace' object has no attribute 'json'.
    for _task_sub in (sc, va, te):
        _task_sub.add_argument("--json", action="store_true", help="structured JSON output")
    tk.set_defaults(func=cmd_task_group)

    ing = add(
        "ingest",
        cmd_ingest,
        "convert external traces (OTel GenAI / OpenAI steps) into ToolTrace trace events",
    )
    ing.add_argument("--format", required=True, choices=["otel-spans", "openai-steps"])
    ing.add_argument("--in", dest="infile", required=True, help="input JSON file")
    ing.add_argument("--out", help="write the JSONL trace to this path")
    ing.add_argument("--task-id", default="ingested/external")
    ing.add_argument("--agent", help="override the agent name recorded in the trace")
    ing.add_argument(
        "--score-against",
        metavar="TASK_ID",
        help="score the ingested trajectory against a task's trace assertions; "
        "assertions needing a workspace are reported as skipped",
    )

    mc = add("mcp-conformance", cmd_mcp_conformance, "check an MCP server against the protocol")
    mc.add_argument(
        "--url", help="reach a hosted server over HTTP instead of starting one over stdio"
    )
    mc.add_argument(
        "command",
        nargs="*",
        help="command that starts the MCP server over stdio; put `--` first if it takes flags, e.g. `mcp-conformance -- python -m my_server` (default: the bundled deterministic fixture)",
    )

    ev = add("evidence", cmd_evidence, "assemble an evidence dossier from bundles")
    ev.add_argument(
        "--bundles", nargs="+", required=True, help="bundle dirs or a directory of them"
    )
    ev.add_argument("--out", help="write evidence.json and evidence.md here")

    ln = add("lint", cmd_lint, "lint task packs for scoring/safety/determinism issues")
    ln.add_argument("--path", help="lint a specific pack directory instead of all packs")

    dr = add("dry-run", cmd_dry_run, "validate a task without invoking any model")
    dr.add_argument("--task", required=True)

    add("self-test", cmd_self_test, "verify harness: cleanup, determinism, timers, integrity")
    pe = add("perturb", cmd_perturb, "inject faults and measure recovery")
    pe.add_argument("--task", required=True)
    pe.add_argument("--agent", default="scripted")
    pe.add_argument("--runs", type=int, default=1)
    pe.add_argument(
        "--perturbation",
        help="extra fault kind[:tool], e.g. tool_failure:read_file or delay",
    )
    pe.add_argument("--out", help="write .tooltrace bundles for each run")
    pe.add_argument("--summary", action="store_true", help="omit per-run results")
    pe.add_argument("--min-recovery-rate", type=float, default=0.0)

    tr = add("trace", cmd_trace, "inspect a bundle trace (filter, assertions, JSONL)")
    tr.add_argument("bundle", help="path to an unpacked .tooltrace bundle directory")
    tr.add_argument("--filter", help="substring filter over the raw event JSON")
    tr.add_argument("--assertions", action="store_true", help="show validation events only")
    tr.add_argument("--limit", type=int, default=50)

    add("snapshot", cmd_snapshot, "generate/verify a hashed dataset snapshot")
    snap = sub.choices["snapshot"]
    snap.add_argument("--source", required=True)
    snap.add_argument("--output", required=True)
    snap.add_argument("--changelog", default="")
    snap.add_argument("--verify", action="store_true")

    srv2 = add("server", cmd_server, "run the self-hosted API server (RBAC/policy/audit)")
    srv2.add_argument("--host", default="127.0.0.1")
    srv2.add_argument("--port", type=int, default=8737)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False):
        from tooltrace.core.versions import FRAMEWORK_VERSION

        print(FRAMEWORK_VERSION)
        return EXIT_OK
    if not hasattr(args, "func"):
        parser.print_help()
        return EXIT_USAGE
    try:
        # args.func is Any off the namespace; bind it so the declared return
        # type of main() is actually enforced rather than laundered through Any.
        exit_code: int = args.func(args)
        return exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
