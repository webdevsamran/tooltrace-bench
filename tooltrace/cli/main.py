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
import sys
import time
from pathlib import Path
from typing import Any

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

    import tooltrace.agents
    import tooltrace.scoring
    import tooltrace.tools  # noqa: F401 - registers tools
    from tooltrace.core.registry import (
        ENTRY_POINT_GROUPS,
        agent_registry,
        discover_plugins,
        scorer_registry,
        tool_registry,
    )
    from tooltrace.tasks import load_all_tasks

    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "tools": sorted(tool_registry.names()),
        "agents": sorted(agent_registry.names()),
        "scorers": sorted(scorer_registry.names()),
        "plugins": {
            kind: sorted(discover_plugins(group)) for kind, group in ENTRY_POINT_GROUPS.items()
        },
    }
    try:
        tasks = load_all_tasks()
        checks["tasks_loaded"] = len(tasks)
        checks["task_packs"] = len({t.pack for t in tasks})
    except Exception as exc:
        checks["tasks_loaded"] = f"ERROR: {exc}"
    ok = isinstance(checks["tasks_loaded"], int) and checks["tasks_loaded"] > 0
    _emit({"ok": ok, **checks}, args.json)  # type: ignore[arg-type]
    return EXIT_OK if ok else EXIT_TASK


def cmd_agents(args: argparse.Namespace) -> int:
    from tooltrace.agents import AgentAdapter  # noqa: F401
    from tooltrace.core.registry import agent_registry

    rows = [
        {"name": n, "class": getattr(a, "__name__", str(a))}
        for n, a in sorted(agent_registry.items())
    ]
    _emit(rows if args.json else chr(10).join(r["name"] for r in rows), args.json)
    return EXIT_OK


def cmd_tasks(args: argparse.Namespace) -> int:
    from tooltrace.tasks import load_all_tasks

    tasks = load_all_tasks()
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]
    rows = [
        {
            "id": t.id,
            "version": t.version,
            "category": t.category,
            "difficulty": t.difficulty.value,
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
    agent_config = json.loads(args.agent_config) if args.agent_config else None
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
        bundle = write_bundle(Path(args.out), result, events, task, diff_text, details)
        payload["bundle"] = bundle.name
    _emit(payload, args.json)
    return EXIT_OK if result.success else EXIT_RUN


def cmd_benchmark(args: argparse.Namespace) -> int:
    from tooltrace.runners.benchmark import run_benchmark
    from tooltrace.tasks import load_all_tasks

    tasks = load_all_tasks()
    if getattr(args, "context_sweep", False):
        return _cmd_context_sweep(args, tasks)
    if args.task:
        wanted = set(args.task.split(","))
        tasks = [t for t in tasks if t.id in wanted]
        missing = wanted - {t.id for t in tasks}
        if missing:
            print(f"error: unknown tasks: {sorted(missing)}", file=sys.stderr)
            return EXIT_TASK
    if not tasks:
        print("error: no tasks selected", file=sys.stderr)
        return EXIT_TASK
    bench = run_benchmark(
        tasks,
        args.agent,
        json.loads(args.agent_config) if args.agent_config else None,
        runs=args.runs,
        out_dir=Path(args.out) if args.out else None,
    )
    payload = bench.model_dump(mode="json")
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


def _cmd_context_sweep(args: argparse.Namespace, tasks: list) -> int:
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
            json.loads(args.agent_config) if args.agent_config else None,
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
    """Run one benchmark per agent and rank them by reliability."""
    from tooltrace.runners.benchmark import run_benchmark
    from tooltrace.tasks import load_all_tasks

    tasks = load_all_tasks()
    if args.task:
        wanted = set(args.task.split(","))
        tasks = [t for t in tasks if t.id in wanted]
    agents = args.agents.split(",")
    standings = []
    for agent in agents:
        config = json.loads(args.agent_config) if args.agent_config else None
        bench = run_benchmark(
            tasks, agent, config, runs=args.runs, out_dir=Path(args.out) if args.out else None
        )
        overall = bench.summary.get("overall", {})
        standings.append(
            {
                "agent": agent,
                "success_rate": overall.get("rate"),
                "ci": [overall.get("ci_low"), overall.get("ci_high")],
                "steps_mean": overall.get("steps_mean"),
                "failed_tool_calls_mean": overall.get("failed_tool_calls_mean"),
                "wall_ms_p95": overall.get("wall_ms_p95"),
            }
        )
    standings.sort(key=lambda s: s["success_rate"] or 0.0, reverse=True)
    _emit(standings, args.json)
    return EXIT_OK


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

    thresholds = json.loads(args.thresholds)
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
        specs = [*specs, PerturbationSpec(kind=kind, params=params)]  # type: ignore[arg-type]
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

            bundle = write_bundle(Path(args.out), result, events, task, diff_text, details)
            runs[-1]["bundle"] = bundle.name

    successes = sum(1 for r in runs if r["recovered"])
    recovery_rate = successes / len(runs)
    payload = {
        "task": task.id,
        "agent": args.agent,
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
    _emit(
        {
            "task_id": args.task_id,
            "format": args.format,
            "agent": agent_name,
            "events": len(events),
            "counts": format_counts(events),
            "failure_rule": str(getattr(reason, "rule", "")),
            "failure_reason": str(getattr(summary_reason, "value", summary_reason)),
            "out": str(args.out) if args.out else None,
        },
        args.json,
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
    p = argparse.ArgumentParser(prog="tooltrace", description=__doc__)
    p.add_argument("--version", action="store_true")
    sub = p.add_subparsers(dest="command")

    def add(name: str, fn, help_: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(func=fn)
        sp.add_argument("--json", action="store_true", help="structured JSON output")
        return sp

    add("doctor", cmd_doctor, "environment and registry health check")
    add("agents", cmd_agents, "list registered agent adapters")

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
    snap = sub.choices["snapshot"]  # type: ignore[union-attr]
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
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
