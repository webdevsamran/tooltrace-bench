"""Verify sandbox isolation guarantees: boundary enforcement, network
default-off policy, env allowlist, timeouts, and full cleanup."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.core.exceptions import PolicyViolation
from tooltrace.core.models import TaskDefinition
from tooltrace.core.registry import tool_registry
from tooltrace.sandbox import TempWorkspaceSandbox
from tooltrace.tools.base import ToolContext, resolve_in_workspace


def main() -> int:
    failures: list[str] = []

    # 1. workspace boundary: escapes are refused by resolve_in_workspace
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        for bad in ("../escape.txt", str(Path(tempfile.gettempdir()) / "x.txt"), "a/../../b"):
            try:
                resolve_in_workspace(ws, bad)
                failures.append(f"boundary: {bad!r} was not denied")
            except PolicyViolation:
                pass

    # 2. network disabled by default in the tool context
    ctx_default = ToolContext(workspace=Path("."))
    if ctx_default.network_policy != "disabled":
        failures.append("network: not disabled by default")

    # 3. environment allowlist attribute exists and defaults to empty
    if ctx_default.env_allowlist != []:
        failures.append("env: default env_allowlist is not empty")

    # 4. timeout enforcement on the shell tool
    shell_cls = tool_registry.get("shell")
    shell = shell_cls() if isinstance(shell_cls, type) else shell_cls
    task = TaskDefinition.model_validate(
        {
            "id": "sandbox-check/selftest",
            "name": "selftest",
            "version": "1.0.0",
            "category": "file-editing",
            "difficulty": "easy",
            "tags": [],
            "objective": "internal check",
            "description": "internal check",
            "starting_workspace": {"a.txt": "hi"},
            "allowed_tools": ["shell"],
            "assertions": [
                {
                    "type": "file_exists",
                    "params": {"path": "a.txt"},
                    "weight": 1.0,
                    "description": "selftest",
                }
            ],
            "expected_artifacts": [],
            "timeout_seconds": 10,
            "max_steps": 4,
            "network_policy": "disabled",
        }
    )
    ws_path: Path | None = None
    with TempWorkspaceSandbox() as sb:
        sb.start(task)
        assert sb.workspace is not None
        ws_path = sb.workspace
        ctx = ToolContext(workspace=sb.workspace)
        result = shell.run(
            {"command": "python -c 'import time; time.sleep(5)'", "timeout_seconds": 1},
            ctx,
        )
        if result.ok:
            failures.append("timeout: sleeping command did not time out")
    # cleanup happens via context manager; workspace must be gone afterwards
    assert ws_path is not None
    if ws_path.exists():
        failures.append("cleanup: temp workspace still exists after cleanup")

    if failures:
        for f in failures:
            print(f"FAIL {f}", file=sys.stderr)
        return 1
    print("sandbox checks passed: boundary, network-default-off, env allowlist, timeout, cleanup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
