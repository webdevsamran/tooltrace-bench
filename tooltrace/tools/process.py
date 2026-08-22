"""Process tools: shell, git, test_runner.

Subprocesses run inside the sandbox workspace with:
- a wall-clock timeout;
- an environment restricted to an allowlist (no secrets leak in);
- sanitized, truncated output.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from tooltrace.core.registry import tool_registry
from tooltrace.tools.base import Tool, ToolContext, ToolResult

NL = chr(10)
MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_ENV_ALLOWLIST = [
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "PYTHONIOENCODING",
    "PYTHONDONTWRITEBYTECODE",
]


def _build_env(ctx: ToolContext) -> dict[str, str]:
    allow = set(DEFAULT_ENV_ALLOWLIST) | set(ctx.env_allowlist)
    return {k: v for k, v in os.environ.items() if k in allow}


def _run(
    cmd: list[str] | str,
    ctx: ToolContext,
    timeout: float,
    shell: bool = False,
) -> tuple[int, str]:
    """Run a subprocess; return (returncode, combined sanitized output)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ctx.workspace),
            env=_build_env(ctx),
            capture_output=True,
            timeout=timeout,
            shell=shell,
        )
        code = proc.returncode
        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        partial_out = (exc.stdout or b"").decode("utf-8", errors="replace")
        partial_err = (exc.stderr or b"").decode("utf-8", errors="replace")
        return 124, (partial_out + partial_err)[:MAX_OUTPUT_BYTES] + NL + "[timeout]"
    except OSError as exc:
        return 127, f"[spawn error] {exc}"
    combined = out if not err else out + NL + err
    return code, combined[:MAX_OUTPUT_BYTES]


@tool_registry.register("shell")
class ShellTool(Tool):
    name: str = "shell"
    description = (
        "Run a shell command inside the workspace. Network is disabled by "
        "task policy; the environment is allowlisted."
    )

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult(ok=False, error="command must be a non-empty string")
        timeout = float(args.get("timeout_seconds", 30.0))  # type: ignore[arg-type]
        code, output = _run(command, ctx, timeout, shell=True)
        ok = code == 0
        return ToolResult(
            ok=ok,
            output=output,
            error=None if ok else f"exit code {code}",
            data={"exit_code": code},
        )


@tool_registry.register("git")
class GitTool(Tool):
    name: str = "git"
    description = "Run `git <args>` inside the workspace repository."

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        git_args = args.get("args")
        if isinstance(git_args, str):
            parts = git_args.split()
        elif isinstance(git_args, list) and all(isinstance(p, str) for p in git_args):
            parts = list(git_args)  # type: ignore[arg-type]
        else:
            return ToolResult(ok=False, error="args must be a string or list of strings")
        forbidden = {"push", "pull", "fetch", "clone", "remote"}
        if parts and parts[0] in forbidden:
            return ToolResult(
                ok=False,
                error=f"git '{parts[0]}' is blocked by task policy (network/remote operations)",
                data={"blocked_subcommand": parts[0]},
            )
        timeout = float(args.get("timeout_seconds", 30.0))  # type: ignore[arg-type]
        code, output = _run(["git", "--no-pager", *parts], ctx, timeout)
        ok = code == 0
        return ToolResult(
            ok=ok,
            output=output,
            error=None if ok else f"git exit code {code}",
            data={"exit_code": code},
        )


@tool_registry.register("test_runner")
class TestRunnerTool(Tool):
    name: str = "test_runner"
    description = (
        "Run the workspace test suite (pytest by default) and report a deterministic pass ratio."
    )

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        target = args.get("path", ".")
        framework = str(args.get("framework", "pytest"))
        timeout = float(args.get("timeout_seconds", 60.0))  # type: ignore[arg-type]
        if framework != "pytest":
            return ToolResult(ok=False, error=f"unsupported test framework: {framework}")
        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            str(target),
        ]
        code, output = _run(cmd, ctx, timeout)
        passed, failed, errors = _parse_pytest_summary(output)
        total = passed + failed + errors
        ratio = (passed / total) if total else None
        return ToolResult(
            ok=code == 0,
            output=output[-4000:],
            error=None if code == 0 else f"pytest exit code {code}",
            data={
                "exit_code": code,
                "passed": passed,
                "failed": failed,
                "errors": errors,
                "pass_ratio": ratio,
            },
        )


def _parse_pytest_summary(output: str) -> tuple[int, int, int]:
    """Parse pytest's short summary line deterministically via regex."""

    def count(pattern: str) -> int:
        m = re.search(pattern, output)
        return int(m.group(1)) if m else 0

    return (
        count(r"(\d+) passed"),
        count(r"(\d+) failed"),
        count(r"(\d+) error"),
    )
