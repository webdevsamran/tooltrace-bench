"""task-lint and dry-run validation (features 27, 28).

``lint_task`` detects ambiguous scoring, unreachable assertions, missing
cleanup declarations, unsafe network use and non-deterministic fixtures.
``dry_run_task`` validates fixtures, assertions and sandbox lifecycle WITHOUT
invoking any AI model.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from tooltrace.core.registry import scorer_registry
from tooltrace.tasks.governance import sha256_text

SEVERITY_ORDER = {"error": 3, "warning": 2, "info": 1}


class LintIssue(BaseModel):
    code: str
    severity: str  # error | warning | info
    message: str


def lint_task(task: Any) -> list[LintIssue]:
    issues: list[LintIssue] = []

    # -- ambiguous scoring ---------------------------------------------------
    weights = [float(a.weight) for a in getattr(task, "assertions", [])]
    if not weights:
        issues.append(
            LintIssue(code="no_assertions", severity="error", message="task has no assertions")
        )
    elif len(set(weights)) > 1 and not str(getattr(task, "objective", "")).strip():
        issues.append(
            LintIssue(
                code="ambiguous_scoring",
                severity="warning",
                message="weighted assertions present but objective text is empty",
            )
        )
    contract = getattr(task, "scoring_contract", None)
    if contract is not None and getattr(contract, "judge_required", False):
        executable = (
            all(scorer_registry.has(a.type) for a in getattr(task, "assertions", []))
            if hasattr(scorer_registry, "has")
            else True
        )
        if executable:
            issues.append(
                LintIssue(
                    code="judge_not_needed",
                    severity="warning",
                    message="judge_required=True but every assertion has a registered deterministic scorer",
                )
            )

    # -- unreachable assertions ----------------------------------------------
    known_paths = set(dict(getattr(task, "starting_workspace", {}) or {})) | set(
        dict(getattr(task, "fixtures", {}) or {})
    )
    for a in getattr(task, "assertions", []):
        if not scorer_registry.has(a.type):
            issues.append(
                LintIssue(
                    code="unknown_scorer",
                    severity="error",
                    message=f"assertion references unregistered scorer '{a.type}'",
                )
            )
            continue
        for key, val in a.params.items():
            if isinstance(val, str) and key in ("path", "file", "target"):
                norm = val.replace("\\", "/").lstrip("./")
                if norm not in known_paths and not any(
                    norm.startswith(k.rstrip("/") + "/") for k in known_paths
                ):
                    issues.append(
                        LintIssue(
                            code="unreachable_assertion",
                            severity="warning",
                            message=f"assertion '{a.type}' targets '{val}' which is neither in the "
                            "starting workspace nor fixtures nor clearly creatable",
                        )
                    )

    # -- unsafe / contradictory network use ----------------------------------
    policy = str(getattr(task, "network_policy", "disabled"))
    tools = list(getattr(task, "allowed_tools", []) or [])
    if "http" in tools and policy == "disabled":
        issues.append(
            LintIssue(
                code="unsafe_network_use",
                severity="error",
                message="http tool allowed while network_policy=disabled; the tool can never succeed",
            )
        )
    if policy == "allowlisted" and not (getattr(task, "metadata", {}) or {}).get("http_allowlist"):
        issues.append(
            LintIssue(
                code="missing_allowlist",
                severity="error",
                message="network_policy=allowlisted but metadata.http_allowlist is empty",
            )
        )

    # -- side-effect declarations vs tools ------------------------------------
    declared = {
        str(se.value) if hasattr(se, "value") else str(se)
        for se in (getattr(task, "allowed_side_effects", []) or [])
    }
    if ("shell" in tools or "git" in tools) and "process_spawn" not in declared:
        issues.append(
            LintIssue(
                code="undeclared_side_effect",
                severity="warning",
                message="shell/git tools allowed but process_spawn side effect not declared",
            )
        )
    if "git" in tools and "git_history_change" not in declared:
        issues.append(
            LintIssue(
                code="missing_cleanup_declaration",
                severity="info",
                message="git tool allowed; declare git_history_change if history rewrites are permitted",
            )
        )

    # -- non-deterministic fixtures -------------------------------------------
    import re as _re

    dateish = _re.compile(r"(20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")
    for path, content in dict(getattr(task, "fixtures", {}) or {}).items():
        hits = dateish.findall(content)
        if hits:
            issues.append(
                LintIssue(
                    code="nondeterministic_fixture",
                    severity="warning",
                    message=f"fixture '{path}' contains wall-clock timestamps {hits[:2]} — "
                    "use deterministic clock injection instead",
                )
            )
    if getattr(task, "seed", None) is None and "random" in str(getattr(task, "tags", [])):
        issues.append(
            LintIssue(
                code="missing_seed",
                severity="error",
                message="task tagged 'random' but has no deterministic seed",
            )
        )
    return issues


def lint_pack(tasks: list[Any]) -> dict[str, list[LintIssue]]:
    return {str(t.id): lint_task(t) for t in tasks}


# ---------------------------------------------------------------------------
# Dry-run (feature 28): validate fixtures/assertions/sandbox without a model
# ---------------------------------------------------------------------------


class DryRunReport(BaseModel):
    task_id: str
    ok: bool
    checks: dict[str, bool] = {}
    problems: list[str] = []


def dry_run_task(task: Any) -> DryRunReport:
    """Validate fixture materialization, assertion resolvability and sandbox
    lifecycle. No agent, no model, no network."""
    problems: list[str] = []
    checks: dict[str, bool] = {}

    # 1. fixtures materialize into a temp workspace
    try:
        with tempfile.TemporaryDirectory(prefix="tooltrace-dryrun-") as td:
            root = Path(td)
            for rel, content in dict(getattr(task, "starting_workspace", {}) or {}).items():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            checks["fixtures_materialize"] = True

            # 2. every assertion's scorer exists and accepts the params shape
            scorer_ok = True
            for a in getattr(task, "assertions", []):
                if not scorer_registry.has(a.type):
                    scorer_ok = False
                    problems.append(f"unregistered scorer: {a.type}")
            checks["assertions_resolvable"] = scorer_ok

            # 3. sandbox lifecycle: start + cleanup through the local provider
            from tooltrace.sandbox.local import TempWorkspaceSandbox

            sb = TempWorkspaceSandbox()
            ws = sb.start(task)
            checks["sandbox_start"] = ws.is_dir()
            sb.cleanup()
            checks["sandbox_cleanup"] = not ws.exists()
    except Exception as exc:  # pragma: no cover - defensive
        checks.setdefault("fixtures_materialize", False)
        problems.append(f"dry-run exception: {exc}")

    ok = all(checks.values()) and not problems
    return DryRunReport(task_id=str(task.id), ok=ok, checks=checks, problems=problems)


__all__ = ["DryRunReport", "LintIssue", "dry_run_task", "lint_pack", "lint_task", "sha256_text"]
