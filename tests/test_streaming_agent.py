"""The streaming adapter drives a local process step by step (#10).

`SubprocessAgent` performs one blocking step, so a trace shows "an agent did
something" and nothing about how. This adapter exchanges NDJSON with a local
process, one event per decision, so the trace records the actual sequence.

These tests drive real child processes rather than mocks: the failure this
adapter is most likely to have is a deadlock between two pipes, and a mock
cannot deadlock.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from tooltrace.agents.streaming import StreamingAgent
from tooltrace.core.models import AgentContext


def _context(**overrides: object) -> AgentContext:
    base: dict[str, object] = {
        "task_id": "demo/task",
        "objective": "fix the typo",
        "description": "",
        "workspace_files": ["config.ini"],
        "allowed_tools": ["read_file", "patch_file"],
        "max_steps": 10,
        "timeout_seconds": 60,
    }
    base.update(overrides)
    return AgentContext(**base)


def _agent_script(tmp_path: Path, body: str) -> str:
    script = tmp_path / "agent.py"
    script.write_text(body, encoding="utf-8")
    # Quote for shlex: tmp_path on Windows contains no spaces here, but the
    # command is user config and should survive a path that does.
    return f'"{sys.executable}" "{script}"'


_ECHO_AGENT = """\
import json, sys

def emit(e):
    sys.stdout.write(json.dumps(e) + "\\n")
    sys.stdout.flush()

task = json.loads(sys.stdin.readline())
emit({"type": "agent_message", "message": "objective: " + task["objective"]})
emit({"type": "usage", "prompt_tokens": 5, "completion_tokens": 2, "model_time_ms": 1.5})
sys.stdin.readline()
emit({"type": "tool_request", "tool": "read_file", "args": {"path": "config.ini"}})
sys.stdin.readline()
emit({"type": "finish", "message": "done", "output": "all good"})
"""


def _run(agent: StreamingAgent, steps: int = 6) -> list:
    """Drive the adapter the way the runner does, until it finishes."""
    actions = []
    observations: list[str] = []
    for step in range(steps):
        action = agent.act(step, observations)
        actions.append(action)
        if action.kind == "finish":
            break
        observations = [f"result of step {step}"] if action.kind == "tool" else []
    return actions


def test_streams_one_action_per_step(tmp_path: Path) -> None:
    agent = StreamingAgent({"command": _agent_script(tmp_path, _ECHO_AGENT)})
    agent.initialize(_context())
    actions = _run(agent)
    agent.finalize()
    assert [a.kind for a in actions] == ["message", "tool", "finish"]
    assert actions[1].tool == "read_file"
    assert actions[1].args == {"path": "config.ini"}


def test_reports_usage_only_when_the_agent_reports_it(tmp_path: Path) -> None:
    agent = StreamingAgent({"command": _agent_script(tmp_path, _ECHO_AGENT)})
    agent.initialize(_context())
    _run(agent)
    outcome = agent.finalize()
    assert outcome.usage.tokens is not None
    assert outcome.usage.tokens.total_tokens == 7
    assert outcome.usage.model_time_ms == pytest.approx(1.5)


_SILENT_AGENT = """\
import json, sys
sys.stdin.readline()
sys.stdout.write(json.dumps({"type": "finish", "output": "quiet"}) + "\\n")
sys.stdout.flush()
"""


def test_absent_usage_is_unknown_not_zero(tmp_path: Path) -> None:
    """Zero tokens and unknown tokens are different claims."""
    agent = StreamingAgent({"command": _agent_script(tmp_path, _SILENT_AGENT)})
    agent.initialize(_context())
    _run(agent)
    outcome = agent.finalize()
    assert outcome.usage.tokens is None
    assert outcome.usage.model_time_ms is None


_MESSAGE_ONLY_AGENT = """\
import json, sys

def emit(e):
    sys.stdout.write(json.dumps(e) + "\\n")
    sys.stdout.flush()

sys.stdin.readline()
for i in range(3):
    emit({"type": "agent_message", "message": "thinking " + str(i)})
    sys.stdin.readline()
emit({"type": "finish", "message": "done"})
"""


def test_consecutive_messages_do_not_deadlock(tmp_path: Path) -> None:
    """The regression that a mock cannot catch.

    An earlier version wrote back only when there were observations, so after
    a message action -- which produces none -- the harness went silent while
    the agent waited for a reply. Both sides blocked forever.
    """
    agent = StreamingAgent({"command": _agent_script(tmp_path, _MESSAGE_ONLY_AGENT)})
    agent.initialize(_context())
    actions = _run(agent, steps=8)
    agent.finalize()
    assert [a.kind for a in actions] == ["message", "message", "message", "finish"]


_NOISY_AGENT = """\
import json, sys

def emit(e):
    sys.stdout.write(json.dumps(e) + "\\n")
    sys.stdout.flush()

sys.stdin.readline()
print("a library logged this")      # not protocol
sys.stdout.flush()
emit({"type": "finish", "message": "done", "output": "ok"})
"""


def test_non_protocol_output_is_recorded_not_fatal(tmp_path: Path) -> None:
    """A stray print must neither end the run nor vanish silently."""
    agent = StreamingAgent({"command": _agent_script(tmp_path, _NOISY_AGENT)})
    agent.initialize(_context())
    actions = _run(agent)
    outcome = agent.finalize()
    assert actions[-1].kind == "finish"
    assert any("a library logged this" in m for m in outcome.messages)


_CRASHING_AGENT = """\
import sys
sys.stdin.readline()
sys.stderr.write("boom: something went wrong\\n")
raise SystemExit(3)
"""


def test_a_dead_agent_finishes_with_an_error_and_keeps_its_stderr(tmp_path: Path) -> None:
    agent = StreamingAgent({"command": _agent_script(tmp_path, _CRASHING_AGENT)})
    agent.initialize(_context())
    actions = _run(agent)
    outcome = agent.finalize()
    assert actions[-1].kind == "finish"
    assert outcome.finish_reason == "error"
    assert any("boom" in m for m in outcome.messages), outcome.messages


def test_a_missing_command_is_rejected_clearly() -> None:
    agent = StreamingAgent({})
    agent.initialize(_context())
    with pytest.raises(ValueError, match="requires a 'command'"):
        agent.act(0, [])


def test_an_unlaunchable_command_names_the_binary() -> None:
    agent = StreamingAgent({"command": "definitely-not-a-real-binary-xyz"})
    agent.initialize(_context())
    with pytest.raises(ValueError, match="definitely-not-a-real-binary-xyz"):
        agent.act(0, [])


def test_the_adapter_is_discoverable_by_name() -> None:
    from tooltrace.core.registry import agent_registry

    assert "streaming" in agent_registry.names()


def test_the_bundled_example_agent_speaks_the_protocol() -> None:
    """The documented example must actually work, not just look plausible."""
    root = Path(__file__).resolve().parent.parent
    example = root / "examples" / "streaming_agent.py"
    assert example.is_file(), "the documented example agent is missing"
    source = example.read_text(encoding="utf-8")
    for event_type in ("tool_request", "agent_message", "finish", "usage"):
        assert event_type in source, f"example never emits {event_type}"
    assert "flush()" in source, "an example that does not flush teaches a deadlock"


def test_json_that_is_not_an_object_is_handled(tmp_path: Path) -> None:
    body = (
        "import json, sys\n"
        "sys.stdin.readline()\n"
        'sys.stdout.write("[1,2,3]\\n"); sys.stdout.flush()\n'
        'sys.stdout.write(json.dumps({"type":"finish","output":"ok"}) + "\\n")\n'
        "sys.stdout.flush()\n"
    )
    agent = StreamingAgent({"command": _agent_script(tmp_path, body)})
    agent.initialize(_context())
    actions = _run(agent)
    outcome = agent.finalize()
    assert actions[-1].kind == "finish"
    assert any("non-object event" in m for m in outcome.messages)


def test_stderr_survives_a_stdin_that_refuses_to_close(tmp_path: Path) -> None:
    """The cross-platform form of a POSIX-only CI failure.

    `_write` swallows a failed flush, so bytes can remain in stdin's buffer
    after the agent has exited; `close()` then retries that flush against a
    pipe with no reader and raises. When close and `communicate()` shared one
    try block, that raise skipped the read and the crashed agent's stderr --
    the only record of why it died -- was silently dropped. Reproduced here by
    making close() raise directly, because Windows will not produce the
    underlying broken pipe.
    """
    agent = StreamingAgent({"command": _agent_script(tmp_path, _CRASHING_AGENT)})
    agent.initialize(_context())
    _run(agent)

    real_stdin = agent._proc.stdin  # type: ignore[union-attr]

    class RefusesToClose:
        def __getattr__(self, item: str) -> object:
            return getattr(real_stdin, item)

        def close(self) -> None:
            raise BrokenPipeError(32, "Broken pipe")

    agent._proc.stdin = RefusesToClose()  # type: ignore[assignment,union-attr]
    outcome = agent.finalize()
    assert any("boom" in m for m in outcome.messages), outcome.messages
