"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

import json
import sys

import pytest
from tooltrace.core.models import TraceEvent


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestSubprocessAgent:
    def test_echo_run(self, tmp_path) -> None:
        from tooltrace.agents.subprocess import SubprocessAgent
        from tooltrace.core.models import AgentContext

        agent = SubprocessAgent(
            config={
                "command": f'"{sys.executable}" -c "print(' + chr(39) + "agent-ok" + chr(39) + ')"',
                "timeout_seconds": 30,
            }
        )
        ctx = AgentContext(
            task_id="t",
            objective="o",
            description="",
            workspace_files=[],
            allowed_tools=[],
            max_steps=4,
            timeout_seconds=30,
            extra={"workspace_path": str(tmp_path)},
        )
        agent.initialize(ctx)
        action = agent.act(0, [])
        assert action.kind == "finish"
        outcome = agent.finalize()
        assert "agent-ok" in outcome.final_output
        assert outcome.finish_reason == "finished"

    def test_missing_command_raises(self, tmp_path) -> None:
        from tooltrace.agents.subprocess import SubprocessAgent
        from tooltrace.core.models import AgentContext

        agent = SubprocessAgent(config={})
        ctx = AgentContext(
            task_id="t",
            objective="o",
            description="",
            workspace_files=[],
            allowed_tools=[],
            max_steps=4,
            timeout_seconds=5,
            extra={"workspace_path": str(tmp_path)},
        )
        agent.initialize(ctx)
        with pytest.raises(ValueError):
            agent.act(0, [])


# ---------------------------------------------------------------------------


class TestOpenAICompat:
    def _ctx(self) -> object:
        from tooltrace.core.models import AgentContext

        return AgentContext(
            task_id="t",
            objective="do it",
            description="d",
            workspace_files=["a.txt"],
            allowed_tools=["read_file"],
            max_steps=4,
            timeout_seconds=10,
            extra={},
        )

    def test_tool_and_finish_actions(self, monkeypatch) -> None:
        import httpx
        from tooltrace.agents.openai_compat import OpenAICompatAgent

        responses = iter(
            [
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "action": "tool",
                                        "tool": "read_file",
                                        "args": {"path": "a.txt"},
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                },
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"action": "finish", "message": "done"})
                            }
                        }
                    ]
                },
            ]
        )

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return next(responses)

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1", "model": "m"})
        agent.initialize(self._ctx())  # type: ignore[arg-type]
        a1 = agent.act(0, [])
        assert a1.kind == "tool" and a1.tool == "read_file"
        a2 = agent.act(1, ["obs"])
        assert a2.kind == "finish" and a2.message == "done"
        usage = agent.finalize().usage
        assert usage.tokens and usage.tokens.total_tokens == 7

    def test_adapter_error_becomes_finish(self, monkeypatch) -> None:
        import httpx
        from tooltrace.agents.openai_compat import OpenAICompatAgent

        class BoomClient:
            def __init__(self, *a, **k):
                raise RuntimeError("no server")

        monkeypatch.setattr(httpx, "Client", BoomClient)
        agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
        agent.initialize(self._ctx())  # type: ignore[arg-type]
        action = agent.act(0, [])
        assert action.kind == "finish" and "adapter error" in action.message

    def test_non_json_content_raises_inside_act(self, monkeypatch) -> None:
        import httpx
        from tooltrace.agents.openai_compat import OpenAICompatAgent

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"choices": [{"message": {"content": "not json"}}]}

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, *a, **k):
                return FakeResp()

        monkeypatch.setattr(httpx, "Client", FakeClient)
        agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
        agent.initialize(self._ctx())  # type: ignore[arg-type]
        action = agent.act(0, [])
        assert action.kind == "finish" and "adapter error" in action.message
