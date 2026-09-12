#!/usr/bin/env python
"""Public symbols nothing in shipped code refers to.

This repository's most common defect, by a wide margin, is code that exists, is
correct, is tested, and that nothing reaches. Found and fixed during the
roadmap build, in roughly this order: `Attachment` declared and never read; a
complete file-queue worker fleet with no way to start it; `sign_bundle`
producing signatures nothing could ask for; `pareto_frontier` with no non-test
caller; the entire `metrics/` package; `apply_retention` described to operators
as a working feature; and `evaluate_policy`, which meant a workspace could
declare allowed providers, models and network modes that the server then
ignored.

Every one of those passed its own tests the whole time. Tests prove a function
works; they say nothing about whether anybody can call it.

So this counts them. A symbol is **reached** if its name appears anywhere in
`tooltrace/`, `scripts/`, `web/src/`, `extensions/`, the workflows, the README
or `pyproject.toml` — anywhere but its own definition line. Tests are excluded
on purpose: a caller that only exists in a test is exactly the defect.

    python scripts/check_reachability.py            # report
    python scripts/check_reachability.py --json
    python scripts/check_reachability.py --check    # exit 1 if it got worse

`ALLOWED` is the honest part. These are unreached *and known*, each with the
reason, and `--check` fails when something new joins them — so the number can
go down without anybody policing it and cannot go up by accident.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "tooltrace"

#: Where a caller could legitimately live. Tests are deliberately absent.
SEARCHED = ("tooltrace", "scripts", "web/src", "extensions", ".github")
SEARCHED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".yml", ".yaml", ".json", ".md", ".toml"}
EXTRA_FILES = ("pyproject.toml", "README.md")

#: Unreached, and correctly so: somebody outside this repository reaches them.
#:
#: An entry here is a claim that a framework calls it, a plugin implements it,
#: or an operator selects it at deployment. Nothing else belongs here.
ALLOWED: dict[str, str] = {
    # Called by pytest itself through the entry point in pyproject.toml.
    "pytest_configure": "pytest plugin hook, invoked by pytest rather than by this package",
    # Implemented by third parties; see docs/plugins.md.
    "ContainerProvider": "sandbox-provider protocol a plugin implements, not one this repo calls",
    "ScoringContext": "part of the scorer contract a plugin receives",
    # Authentication providers are chosen by the operator at deployment.
    "LocalDevAuthProvider": "auth provider selected by a deployment, not wired by default",
    "OIDCProviderHook": "auth provider selected by a deployment, not wired by default",
}

#: Unreached, and **not** correctly so: written ahead of a caller.
#:
#: This is a debt register, not an exemption list. Everything here works and is
#: tested; nothing a user can type reaches any of it. Kept separate from
#: `ALLOWED` because the two mean opposite things, and a single list would let
#: the second quietly borrow the first's legitimacy -- which is how
#: `evaluate_policy` sat unreferenced while the console told operators that
#: policy governed their workspace.
#:
#: The rule for this list is one-directional: entries may leave, by being wired
#: or deleted. `--check` fails on anything new.
KNOWN_UNREACHED: dict[str, str] = {
    # A provider-interop layer built before the adapters that would use it. The
    # three shipping HTTP adapters share `chat_base.py` instead.
    "adapter_health_check": "interop layer; the shipping adapters use chat_base.py",
    "build_provider_request": "interop layer; the shipping adapters use chat_base.py",
    "negotiate": "interop layer; the shipping adapters use chat_base.py",
    "normalize_model_metadata": "interop layer; the shipping adapters use chat_base.py",
    "parse_provider_tool_call": "interop layer; the shipping adapters use chat_base.py",
    "run_with_retries": "interop layer; the shipping adapters use chat_base.py",
    # Container/fault infrastructure ahead of the Docker sandbox that would use it.
    "FaultInjectingProxy": "container fault infrastructure; no sandbox path drives it yet",
    "detect_container_runtime": "container fault infrastructure; no sandbox path drives it yet",
    "frozen_time": "deterministic-clock helper; no runner path uses it yet",
    "recovery_score": "superseded by analysis/behaviour.py recovery_quality, which is wired",
    "sample_resource_usage": "resource sampling; nothing records it into a bundle yet",
    # Dataset governance: snapshots, provenance and contamination, with a CLI
    # surface for `snapshot` only.
    "assess_contamination": "dataset governance; only `snapshot` has a CLI surface",
    "build_pack_index": "dataset governance; only `snapshot` has a CLI surface",
    "build_provenance_manifest": "dataset governance; only `snapshot` has a CLI surface",
    "build_snapshot": "dataset governance; only `snapshot` has a CLI surface",
    "find_duplicates": "dataset governance; only `snapshot` has a CLI surface",
    "satisfies_range": "semver range helper for pack indexes, which have no CLI surface",
    "verify_provenance_manifest": "dataset governance; only `snapshot` has a CLI surface",
    "ContaminationRisk": "declared on TaskDefinitionV2; no task sets it and nothing reads it",
    # Suite manifests: the selection machinery predates `--task`/`--limit`.
    "build_suite": "suite manifests; task selection ships as --task/--limit/--shuffle instead",
    "sample_suite": "suite manifests; task selection ships as --task/--limit/--shuffle instead",
    # Individually orphaned.
    "agency_report": "aggregate over excessive_agency/blast_radius, which are wired individually",
    "aggregate_pass_at_k": "superseded by the summary path in runners/benchmark.py",
    "require_verified": "guard for a reproduction path that calls verify directly instead",
    "windows_are_comparable": "comparability guard; cmd_online reports the cursor without it",
}


def python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def public_definitions() -> dict[str, tuple[str, int]]:
    """name -> (module, line) for every public module-level def/class."""
    found: dict[str, tuple[str, int]] = {}
    for path in python_files(PACKAGE):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            is_definition = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
            if is_definition and not node.name.startswith("_"):
                found[node.name] = (path.relative_to(ROOT).as_posix(), node.lineno)
    return found


def searchable_text() -> dict[str, str]:
    files: dict[str, str] = {}
    for area in SEARCHED:
        base = ROOT / area
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_dir() or "__pycache__" in path.parts or "node_modules" in path.parts:
                continue
            if path.suffix not in SEARCHED_SUFFIXES:
                continue
            # This file names every allowlisted symbol in `ALLOWED`, and it
            # lives under `scripts/`. Left in the corpus, each allowance makes
            # its own symbol look reached -- and the first run reported all five
            # as stale for exactly that reason. A mention in bookkeeping is not
            # a call.
            if path.resolve() == Path(__file__).resolve():
                continue
            files[path.relative_to(ROOT).as_posix()] = path.read_text(
                encoding="utf-8", errors="replace"
            )
    for extra in EXTRA_FILES:
        target = ROOT / extra
        if target.is_file():
            files[extra] = target.read_text(encoding="utf-8", errors="replace")
    return files


def unreached() -> list[tuple[str, str]]:
    """(symbol, module) for every public symbol nothing refers to."""
    definitions = public_definitions()
    corpus = searchable_text()
    orphans: list[tuple[str, str]] = []
    for name, (home, lineno) in sorted(definitions.items()):
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        referenced = False
        for path, text in corpus.items():
            for number, line in enumerate(text.splitlines(), start=1):
                if path == home and number == lineno:
                    continue  # the definition is not a reference to itself
                if pattern.search(line):
                    referenced = True
                    break
            if referenced:
                break
        if not referenced:
            orphans.append((name, home))
    return orphans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 when something unreached is not in ALLOWED",
    )
    args = parser.parse_args(argv)

    orphans = unreached()
    total = len(public_definitions())
    known = {**ALLOWED, **KNOWN_UNREACHED}
    unexpected = [(n, m) for n, m in orphans if n not in known]
    stale = sorted(set(known) - {n for n, _ in orphans})

    payload = {
        "public_symbols": total,
        "unreached": [{"symbol": n, "module": m} for n, m in orphans],
        "legitimately_unreachable": len(ALLOWED),
        "debt": sorted(KNOWN_UNREACHED),
        "unexpected": [{"symbol": n, "module": m} for n, m in unexpected],
        "stale_allowances": stale,
        "statement": (
            f"{len(orphans)} of {total} public symbols are referenced nowhere outside their own "
            f"definition: {len(ALLOWED)} reached from outside this repository, "
            f"{len(KNOWN_UNREACHED)} written ahead of a caller, {len(unexpected)} unaccounted for"
            + (f"; {len(stale)} allowance(s) no longer describe anything" if stale else "")
            + "."
        ),
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(payload["statement"])
        if unexpected:
            print("\nUnreached and not allowlisted:")
            for name, module in unexpected:
                print(f"  {module}: {name}")
        if stale:
            print(f"\nAllowances that no longer describe anything: {stale}")

    if args.check:
        # A stale allowance is a failure too: it sits there as pre-approval for
        # a name somebody may reuse for something quite different.
        return 1 if unexpected or stale else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
