"""Three wire formats, one loop -- and the history that was never kept.

`openai_compat` declared a `_messages` list, sent it on every request, and never
appended to it. A model was therefore asked to act on the last five
*observations* with no record of what it had itself decided -- "file not found",
with no memory of which file it asked for -- and `AgentOutcome.messages` came
back empty from every real run. That is the same defect this repository keeps
finding in itself: a field that exists, is read, and is never written.

The provider halves are tested against recorded response shapes rather than live
endpoints. That is deliberate and it is a real limitation: these tests prove the
adapter builds the request each API documents and reads the reply each API
returns. They cannot prove the API still looks like that. What they can prove is
the class of bug that actually bites -- `content[0]` on a response whose first
block is `thinking`, `role: assistant` sent to an API that only accepts `model`
-- and each of those is pinned below.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from tooltrace.agents.anthropic import AnthropicAgent
from tooltrace.agents.chat_base import HISTORY_TURNS, ChatProtocolAgent
from tooltrace.agents.gemini import GeminiAgent
from tooltrace.agents.openai_compat import OpenAICompatAgent
from tooltrace.core.models import AgentContext
from tooltrace.core.registry import agent_registry

TOOL_CALL = json.dumps({"action": "tool", "tool": "read_file", "args": {"path": "a.txt"}})
FINISH = json.dumps({"action": "finish", "message": "done"})


def context() -> AgentContext:
    return AgentContext(
        task_id="p/one",
        objective="do the thing",
        description="",
        workspace_files=["a.txt"],
        allowed_tools=["read_file"],
        max_steps=4,
        timeout_seconds=10,
    )


class Recorder:
    """Captures every request body and replies with a queued response."""

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []
        self.headers: list[dict[str, str]] = []
        self.urls: list[str] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        recorder = self

        class FakeResponse:
            def __init__(self, payload: dict[str, Any]) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, Any]:
                return self._payload

        class FakeClient:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def __enter__(self) -> FakeClient:
                return self

            def __exit__(self, *args: object) -> bool:
                return False

            def post(self, url: str, **kwargs: Any) -> FakeResponse:
                recorder.urls.append(url)
                recorder.requests.append(kwargs.get("json") or {})
                recorder.headers.append(kwargs.get("headers") or {})
                return FakeResponse(recorder.replies.pop(0))

        monkeypatch.setattr(httpx, "Client", FakeClient)


def openai_reply(content: str, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    reply: dict[str, Any] = {"choices": [{"message": {"content": content}}]}
    if usage:
        reply["usage"] = usage
    return reply


# --- the history that was never kept ----------------------------------------


def test_the_second_turn_carries_what_the_model_said_on_the_first(monkeypatch) -> None:
    """The defect: `_messages` was sent every turn and appended to never."""
    recorder = Recorder([openai_reply(TOOL_CALL), openai_reply(FINISH)])
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
    agent.initialize(context())
    agent.act(0, [])
    agent.act(1, ["read_file: file not found"])

    second = recorder.requests[1]["messages"]
    assert any(m["role"] == "assistant" and "read_file" in m["content"] for m in second), (
        "the model cannot tell which file it asked for without its own prior turn"
    )


def test_the_first_turn_carries_no_history(monkeypatch) -> None:
    recorder = Recorder([openai_reply(TOOL_CALL)])
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
    agent.initialize(context())
    agent.act(0, [])
    roles = [m["role"] for m in recorder.requests[0]["messages"]]
    assert roles == ["system", "user"]


def test_finalize_returns_what_the_model_actually_said(monkeypatch) -> None:
    """It returned `[]` from every real run, because nothing was ever recorded."""
    recorder = Recorder([openai_reply(TOOL_CALL), openai_reply(FINISH)])
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
    agent.initialize(context())
    agent.act(0, [])
    agent.act(1, ["obs"])
    outcome = agent.finalize()
    assert len(outcome.messages) == 2
    assert outcome.final_output == FINISH


def test_a_malformed_reply_does_not_enter_the_history(monkeypatch) -> None:
    """A turn the model got wrong is not something to reason from next turn."""
    recorder = Recorder([openai_reply("not json"), openai_reply(FINISH)])
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
    agent.initialize(context())
    action = agent.act(0, [])
    assert action.kind == "finish" and "adapter error" in action.message
    agent.act(1, ["obs"])
    assert [m["role"] for m in recorder.requests[1]["messages"]] == ["system", "user"]


def test_the_history_is_bounded(monkeypatch) -> None:
    """An unbounded transcript grows the prompt every step.

    A benchmark that quietly triples its own token cost on a long task is
    measuring its own accumulation.
    """
    turns = HISTORY_TURNS + 5
    recorder = Recorder([openai_reply(TOOL_CALL) for _ in range(turns)])
    recorder.install(monkeypatch)
    agent = OpenAICompatAgent(config={"base_url": "http://localhost:9/v1"})
    agent.initialize(context())
    for step in range(turns):
        agent.act(step, ["obs"])
    sent = recorder.requests[-1]["messages"]
    assert len(sent) <= HISTORY_TURNS * 2 + 2


# --- Anthropic --------------------------------------------------------------


def anthropic_reply(blocks: list[dict[str, Any]], usage: dict[str, Any] | None = None):
    reply: dict[str, Any] = {"content": blocks}
    if usage:
        reply["usage"] = usage
    return reply


def test_anthropic_puts_the_system_prompt_at_the_top_level(monkeypatch) -> None:
    """A `role: system` message is rejected by this API."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recorder = Recorder([anthropic_reply([{"type": "text", "text": FINISH}])])
    recorder.install(monkeypatch)
    agent = AnthropicAgent(config={"model": "claude-sonnet-5"})
    agent.initialize(context())
    agent.act(0, [])
    body = recorder.requests[0]
    assert "system" in body and body["system"].startswith("You are an autonomous")
    assert all(m["role"] != "system" for m in body["messages"])


def test_anthropic_always_sends_max_tokens(monkeypatch) -> None:
    """The API rejects a request without it, so a default is not optional."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recorder = Recorder([anthropic_reply([{"type": "text", "text": FINISH}])])
    recorder.install(monkeypatch)
    agent = AnthropicAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    assert recorder.requests[0]["max_tokens"] > 0


def test_anthropic_sends_a_pinned_version_header(monkeypatch) -> None:
    """A benchmark that moves when a provider changes its default is measuring that."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recorder = Recorder([anthropic_reply([{"type": "text", "text": FINISH}])])
    recorder.install(monkeypatch)
    agent = AnthropicAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    assert recorder.headers[0]["anthropic-version"] == "2023-06-01"
    assert recorder.headers[0]["x-api-key"] == "test-key"


def test_anthropic_skips_a_leading_thinking_block(monkeypatch) -> None:
    """`content[0]` works until the model thinks first, then everything breaks."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recorder = Recorder(
        [
            anthropic_reply(
                [
                    {"type": "thinking", "thinking": "considering the options"},
                    {"type": "text", "text": FINISH},
                ]
            )
        ]
    )
    recorder.install(monkeypatch)
    agent = AnthropicAgent(config={})
    agent.initialize(context())
    action = agent.act(0, [])
    assert action.kind == "finish" and action.message == "done"


def test_anthropic_reports_cache_tokens(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    recorder = Recorder(
        [
            anthropic_reply(
                [{"type": "text", "text": FINISH}],
                usage={
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 60,
                    "cache_creation_input_tokens": 5,
                },
            )
        ]
    )
    recorder.install(monkeypatch)
    agent = AnthropicAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    tokens = agent.finalize().usage.tokens
    assert tokens is not None
    assert tokens.cached_prompt_tokens == 60
    assert tokens.cache_write_tokens == 5


def test_anthropic_without_a_key_says_where_it_looked(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = AnthropicAgent(config={})
    agent.initialize(context())
    action = agent.act(0, [])
    assert "ANTHROPIC_API_KEY" in action.message


# --- Gemini -----------------------------------------------------------------


def gemini_reply(text: str, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    reply: dict[str, Any] = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if usage:
        reply["usageMetadata"] = usage
    return reply


def test_gemini_spells_the_assistant_role_model(monkeypatch) -> None:
    """`role: assistant` is rejected outright by this API."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = Recorder([gemini_reply(TOOL_CALL), gemini_reply(FINISH)])
    recorder.install(monkeypatch)
    agent = GeminiAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    agent.act(1, ["obs"])
    roles = [turn["role"] for turn in recorder.requests[1]["contents"]]
    assert "model" in roles
    assert "assistant" not in roles


def test_gemini_keeps_the_key_out_of_the_url(monkeypatch) -> None:
    """A key in a query string ends up in proxy logs and error reports."""
    monkeypatch.setenv("GEMINI_API_KEY", "secret-value")
    recorder = Recorder([gemini_reply(FINISH)])
    recorder.install(monkeypatch)
    agent = GeminiAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    assert "secret-value" not in recorder.urls[0]
    assert recorder.headers[0]["x-goog-api-key"] == "secret-value"


def test_gemini_asks_for_json(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = Recorder([gemini_reply(FINISH)])
    recorder.install(monkeypatch)
    agent = GeminiAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    config = recorder.requests[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json"


def test_gemini_translates_its_usage_field_names(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = Recorder(
        [
            gemini_reply(
                FINISH,
                usage={
                    "promptTokenCount": 40,
                    "candidatesTokenCount": 12,
                    "totalTokenCount": 52,
                    "cachedContentTokenCount": 30,
                },
            )
        ]
    )
    recorder.install(monkeypatch)
    agent = GeminiAgent(config={})
    agent.initialize(context())
    agent.act(0, [])
    tokens = agent.finalize().usage.tokens
    assert tokens is not None
    assert (tokens.prompt_tokens, tokens.completion_tokens) == (40, 12)
    assert tokens.cached_prompt_tokens == 30
    assert tokens.cache_write_tokens is None, "this API reports no cache-write count"


def test_gemini_names_the_block_reason_when_there_are_no_candidates(monkeypatch) -> None:
    """A refusal arrives as an empty list, which otherwise reads as a transport failure."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    recorder = Recorder([{"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}])
    recorder.install(monkeypatch)
    agent = GeminiAgent(config={})
    agent.initialize(context())
    action = agent.act(0, [])
    assert "SAFETY" in action.message


def test_gemini_without_a_key_says_where_it_looked(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    agent = GeminiAgent(config={})
    agent.initialize(context())
    assert "GEMINI_API_KEY" in agent.act(0, []).message


# --- one loop, three providers ----------------------------------------------


@pytest.mark.parametrize("name", ["openai_compat", "anthropic", "gemini"])
def test_every_provider_adapter_is_registered(name: str) -> None:
    assert agent_registry.has(name)


@pytest.mark.parametrize("cls", [OpenAICompatAgent, AnthropicAgent, GeminiAgent])
def test_every_provider_adapter_shares_the_loop(cls: type) -> None:
    """Three copies of the loop would drift, and the drift would be invisible.

    Each adapter would keep working, and a comparison between two models would
    quietly become a comparison between two prompts.
    """
    assert issubclass(cls, ChatProtocolAgent)
    assert cls.act is ChatProtocolAgent.act
    assert cls.system_prompt is ChatProtocolAgent.system_prompt


def test_all_three_send_the_same_system_prompt(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    prompts = []
    for cls, replies, extract in [
        (
            OpenAICompatAgent,
            [openai_reply(FINISH)],
            lambda body: body["messages"][0]["content"],
        ),
        (
            AnthropicAgent,
            [anthropic_reply([{"type": "text", "text": FINISH}])],
            lambda b: b["system"],
        ),
        (GeminiAgent, [gemini_reply(FINISH)], lambda b: b["systemInstruction"]["parts"][0]["text"]),
    ]:
        recorder = Recorder(replies)
        recorder.install(monkeypatch)
        agent = cls(config={"base_url": "http://localhost:9/v1"})
        agent.initialize(context())
        agent.act(0, [])
        prompts.append(extract(recorder.requests[0]))
    assert len(set(prompts)) == 1, "the prompt must not vary by provider"
