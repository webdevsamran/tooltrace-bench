"""Streaming agent adapter: consume per-step events from a local process.

``SubprocessAgent`` runs a command once and captures its stdout. That is
honest but opaque: the whole run is a single step, so the trace records "an
agent did something" and nothing about how it got there. This adapter is the
per-step counterpart. It launches a local agent process and exchanges
newline-delimited JSON with it over stdin/stdout: the agent emits one event
per decision, the harness writes each tool observation back, and the loop
continues until the agent finishes or the step budget runs out.

Everything stays on the machine -- it is a child process, not a network call
-- so it works with no connectivity at all, and the protocol is plain NDJSON
rather than a vendor SDK, so any framework that can print a line of JSON can
be driven by it.

Config::

    {
      "command": "python my_agent.py",
      "env": {"MY_AGENT_MODEL": "qwen2.5"}
    }

Protocol. One JSON object per line on the agent's stdout::

    {"type": "tool_request", "tool": "read_file", "args": {"path": "a.txt"}}
    {"type": "agent_message", "message": "checking the config first"}
    {"type": "finish", "message": "done", "output": "fixed the typo"}
    {"type": "usage", "prompt_tokens": 12, "completion_tokens": 8,
     "model_time_ms": 40.0}

and one object per line written to its stdin::

    {"type": "task", "objective": "...", "allowed_tools": [...], ...}
    {"type": "observation", "step": 3, "observations": ["...", "..."]}
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from typing import Any, Literal

from tooltrace.agents.base import AgentAdapter
from tooltrace.core.models import (
    AgentAction,
    AgentContext,
    AgentOutcome,
    TokenUsage,
    UsageMetadata,
)
from tooltrace.tools.process import DEFAULT_ENV_ALLOWLIST


def _split_command(command: str) -> list[str]:
    r"""Split a command string into argv, correctly on Windows too.

    shlex in POSIX mode treats a backslash as an escape, which mangles
    ``C:\path\python.exe``. In non-POSIX mode backslashes survive but the
    quotes do *not* get stripped, so a quoted path arrives as
    ``'"C:\path\python.exe"'`` and the executable is not found -- quoting a
    path containing spaces, the one case quoting exists for, is exactly what
    breaks. Neither mode is right on its own: use non-POSIX and strip the
    quotes afterwards.
    """
    posix = os.name != "nt"
    parts = shlex.split(command, posix=posix)
    if posix:
        return parts
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


class StreamingAgent(AgentAdapter):
    """Drive a local agent process that emits one JSON event per step."""

    name = "streaming"

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._messages: list[str] = []
        self._final_output = ""
        self._finish_reason: Literal["finished", "max_steps", "timeout", "error", "aborted"] = (
            "finished"
        )
        self._model_time_ms = 0.0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._saw_usage = False
        self._proc: subprocess.Popen[str] | None = None
        self._started = False

    # -- process lifecycle ---------------------------------------------------

    def _env(self) -> dict[str, str]:
        # The same allowlist the shell tool uses. An agent process should not
        # inherit the harness's whole environment, which may hold credentials
        # that have nothing to do with the task.
        env = {k: v for k, v in os.environ.items() if k in DEFAULT_ENV_ALLOWLIST}
        extra = self.config.get("env")
        if isinstance(extra, dict):
            env.update({str(k): str(v) for k, v in extra.items()})
        return env

    def _start(self) -> None:
        command = self.config.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ValueError(
                "streaming adapter requires a 'command' in agent config, for "
                'example {"command": "python my_agent.py"}'
            )
        argv = _split_command(command)
        workspace = self._ctx.extra.get("workspace") if self._ctx.extra else None
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # line buffered: per-step events are the point
                cwd=str(workspace) if workspace else None,
                env=self._env(),
            )
        except OSError as exc:
            raise ValueError(f"streaming adapter could not start {argv[0]!r}: {exc}") from exc
        self._started = True
        self._write(
            {
                "type": "task",
                "task_id": self._ctx.task_id,
                "objective": self._ctx.objective,
                "description": self._ctx.description,
                "allowed_tools": list(self._ctx.allowed_tools),
                "workspace_files": list(self._ctx.workspace_files),
                "max_steps": self._ctx.max_steps,
            }
        )

    def _write(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(json.dumps(payload) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            # The agent exited. Not an error here; the next read reports it.
            pass

    def _read_event(self) -> dict[str, Any] | None:
        """Read one JSON event, skipping blank and unparseable lines.

        A line the agent did not intend as protocol -- a stray print, a
        warning from a library -- must not end the run. It is recorded as a
        message and the loop continues. Swallowing it silently would hide an
        agent misbehaving; aborting on it would make the adapter unusable with
        anything that logs.
        """
        if self._proc is None or self._proc.stdout is None:
            return None
        while True:
            line = self._proc.stdout.readline()
            if line == "":
                return None  # EOF: the process ended
            stripped = line.strip()
            if not stripped:
                continue
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError:
                self._messages.append(f"[non-protocol output] {stripped[:500]}")
                continue
            if isinstance(event, dict):
                return event
            self._messages.append(f"[non-object event] {stripped[:500]}")

    # -- adapter API ---------------------------------------------------------

    def act(self, step: int, observations: list[str]) -> AgentAction:
        started = time.perf_counter()
        if not self._started:
            self._start()
        else:
            # Written on *every* turn, including when there are no
            # observations. Writing only when observations exist deadlocks:
            # after the agent returns a message rather than a tool call there
            # is nothing to report, so the harness stayed silent while the
            # agent sat waiting for a reply that was never coming. The
            # protocol is simpler to implement correctly if the harness always
            # answers.
            self._write({"type": "observation", "step": step, "observations": observations})

        while True:
            event = self._read_event()
            if event is None:
                # The process ended without saying goodbye. If it had produced
                # a final output the run is complete; otherwise it died.
                self._finish_reason = "finished" if self._final_output else "error"
                return AgentAction(kind="finish", message=self._final_output)

            kind = str(event.get("type", ""))

            # Usage may arrive at any point and accumulates across the run.
            if kind == "usage":
                self._saw_usage = True
                self._prompt_tokens += int(event.get("prompt_tokens") or 0)
                self._completion_tokens += int(event.get("completion_tokens") or 0)
                self._model_time_ms += float(event.get("model_time_ms") or 0.0)
                continue

            elapsed = (time.perf_counter() - started) * 1000.0
            delta = UsageMetadata(model_time_ms=round(elapsed, 3))

            if kind == "tool_request":
                tool = event.get("tool")
                if not isinstance(tool, str) or not tool:
                    self._messages.append("[malformed tool_request: no tool name]")
                    continue
                args = event.get("args")
                return AgentAction(
                    kind="tool",
                    tool=tool,
                    args=dict(args) if isinstance(args, dict) else {},
                    message=str(event.get("message", "")),
                    usage_delta=delta,
                )

            if kind == "agent_message":
                message = str(event.get("message", ""))
                self._messages.append(message)
                return AgentAction(kind="message", message=message, usage_delta=delta)

            if kind == "finish":
                self._final_output = str(event.get("output", event.get("message", "")))
                message = str(event.get("message", ""))
                if message:
                    self._messages.append(message)
                self._finish_reason = "finished"
                return AgentAction(kind="finish", message=message, usage_delta=delta)

            self._messages.append(f"[unknown event type {kind!r}]")

    def finalize(self) -> AgentOutcome:
        stderr_tail = ""
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
                self._proc.terminate()
                _, stderr_tail = self._proc.communicate(timeout=10)
            except (subprocess.TimeoutExpired, OSError, ValueError):
                self._proc.kill()
            finally:
                self._proc = None
        if stderr_tail and stderr_tail.strip():
            # Surfaced rather than dropped: an agent that crashed after its
            # last event leaves its explanation here and nowhere else.
            self._messages.append(f"[agent stderr] {stderr_tail.strip()[:2000]}")

        # Tokens are reported only when the agent reported them. A zero would
        # be indistinguishable from "this agent used no tokens", which is a
        # different claim from "we do not know".
        tokens = (
            TokenUsage(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                total_tokens=self._prompt_tokens + self._completion_tokens,
            )
            if self._saw_usage
            else None
        )
        return AgentOutcome(
            messages=list(self._messages),
            artifacts={},
            final_output=self._final_output,
            finish_reason=self._finish_reason,
            usage=UsageMetadata(
                tokens=tokens,
                model_time_ms=round(self._model_time_ms, 3) if self._saw_usage else None,
            ),
        )


__all__ = ["StreamingAgent"]
