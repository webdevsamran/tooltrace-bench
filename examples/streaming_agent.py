#!/usr/bin/env python3
"""A minimal streaming agent, as a reference for the `streaming` adapter.

Run it with::

    tooltrace run --task file-editing/fix-config-typo --agent streaming \
      --agent-config '{"command": "python examples/streaming_agent.py"}'

It speaks the NDJSON protocol on stdin/stdout and needs no network, no model
and no dependencies -- the point is to show the shape of the exchange, not to
be clever. A real agent replaces `decide()` with whatever it uses to think;
everything else stays the same.
"""

from __future__ import annotations

import json
import sys


def emit(event: dict[str, object]) -> None:
    """One JSON object per line, flushed immediately.

    The flush matters: without it the harness blocks waiting for a step the
    agent has already decided, and a streaming adapter degrades into the
    blocking one it exists to replace.
    """
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def read_event() -> dict[str, object] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def decide(step: int, objective: str, observations: list[str]) -> dict[str, object]:
    """Pick the next action. Deliberately simple and deterministic."""
    if step == 0:
        return {"type": "agent_message", "message": f"objective: {objective}"}
    if step == 1:
        return {"type": "tool_request", "tool": "read_file", "args": {"path": "config.ini"}}
    if step == 2:
        return {
            "type": "tool_request",
            "tool": "patch_file",
            "args": {"path": "config.ini", "search": "timout", "replace": "timeout"},
        }
    return {"type": "finish", "message": "typo corrected", "output": "config.ini fixed"}


def main() -> int:
    task = read_event() or {}
    objective = str(task.get("objective", ""))

    step = 0
    observations: list[str] = []
    while True:
        action = decide(step, objective, observations)
        emit(action)
        # Report usage alongside each decision. A real agent would emit real
        # numbers here; reporting none at all is also valid, and the harness
        # records "unknown" rather than zero.
        emit({"type": "usage", "prompt_tokens": 10, "completion_tokens": 4, "model_time_ms": 1.0})
        if action.get("type") == "finish":
            return 0

        incoming = read_event()
        if incoming is None:
            return 0  # harness closed the pipe
        if incoming.get("type") == "observation":
            raw = incoming.get("observations")
            observations = [str(o) for o in raw] if isinstance(raw, list) else []
        step += 1


if __name__ == "__main__":
    raise SystemExit(main())
