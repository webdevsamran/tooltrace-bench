"""Subprocess agent adapter: run any agent CLI inside the workspace.

Config:
    {"command": "my-agent --task {objective}", "timeout_seconds": 120}

The command runs once with ``cwd`` set to the sandbox workspace. Its stdout
is captured as the final output. This adapter is opaque: it performs one
blocking step and cannot be steered mid-run, which the trace records
honestly.
"""

from __future__ import annotations

import os
import subprocess
import time

from tooltrace.agents.base import AgentAdapter
from tooltrace.core.models import AgentAction, AgentContext, AgentOutcome, UsageMetadata
from tooltrace.tools.process import DEFAULT_ENV_ALLOWLIST


class SubprocessAgent(AgentAdapter):
    name = "subprocess"

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._ran = False
        self._output = ""
        self._error: str | None = None
        self._wall_ms = 0.0

    def _build_command(self) -> str:
        command = str(self.config.get("command", "")).strip()
        if not command:
            raise ValueError("subprocess agent requires config 'command'")
        return command.format(
            objective=self._ctx.objective,
            task_id=self._ctx.task_id,
        )

    def act(self, step: int, observations: list[str]) -> AgentAction:
        if self._ran:
            return AgentAction(kind="finish", message=self._output)
        self._ran = True
        command = self._build_command()
        timeout = float(
            self.config.get("timeout_seconds", self._ctx.timeout_seconds)  # type: ignore[arg-type]
        )
        env = {k: v for k, v in os.environ.items() if k in set(DEFAULT_ENV_ALLOWLIST)}
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                command,
                cwd=str(self._workspace_path()),
                env=env,
                capture_output=True,
                timeout=timeout,
                shell=True,
                text=True,
            )
            self._wall_ms = (time.perf_counter() - start) * 1000.0
            self._output = proc.stdout[-32 * 1024 :]
            if proc.returncode != 0:
                self._error = f"exit code {proc.returncode}: {proc.stderr[-2000:]}"
        except subprocess.TimeoutExpired:
            self._wall_ms = (time.perf_counter() - start) * 1000.0
            self._error = "subprocess timed out"
        except OSError as exc:
            self._error = f"spawn error: {exc}"
        return AgentAction(kind="finish", message=self._output)

    def _workspace_path(self) -> str:
        return str(self._ctx.extra.get("workspace_path", "."))

    def finalize(self) -> AgentOutcome:
        finish = "error" if self._error else "finished"
        return AgentOutcome(
            messages=[self._output] if self._output else [],
            final_output=self._output,
            finish_reason=finish,  # type: ignore[arg-type]
            usage=UsageMetadata(model_time_ms=self._wall_ms or None),
        )
