"""The half of an HTTP agent adapter that is not provider-specific.

Three providers, one loop. What differs between OpenAI, Anthropic and Gemini is
the URL, the headers, the request body and where the text and the token counts
are found in the reply. What does not differ is the system prompt, the tool
catalogue, the conversation history, the JSON protocol the model answers in, or
the translation of that answer into an :class:`AgentAction`.

Keeping the loop in one place is not tidiness. Three copies of it would drift,
and a drift here is invisible: each adapter would keep working, and a comparison
between two models would quietly become a comparison between two prompts.

**The history is the reason this file exists at all.** `openai_compat` declared
a `_messages` list, sent it on every request, and never appended to it. So a
model was asked to act on the last five *observations* with no record of what it
had itself decided -- "file not found" with no memory of which file it asked for
-- and `AgentOutcome.messages` came back empty from every real run.
"""

from __future__ import annotations

import json
import time
from abc import abstractmethod
from typing import Any

from tooltrace.agents.base import AgentAdapter
from tooltrace.core.models import (
    AgentAction,
    AgentContext,
    AgentOutcome,
    TokenUsage,
    UsageMetadata,
)

SYSTEM_PROMPT = """You are an autonomous coding agent operating inside a sandboxed workspace.

Available tools (argument names, `?` marks optional):
{tools}

Respond with EXACTLY one JSON object and nothing else:
{{"action": "tool", "tool": "<tool name>", "args": {{...}}}}
or, when the task is complete:
{{"action": "finish", "message": "<summary>"}}

Objective: {objective}
Task description: {description}
Workspace files: {files}
"""

#: Turns of history sent back to the model. Bounded because an unbounded
#: transcript grows the prompt every step, and a benchmark that quietly triples
#: its own token cost on long tasks is measuring its own accumulation.
HISTORY_TURNS = 12


def add_counts(previous: int | None, reported: int | None) -> int | None:
    """Accumulate across turns, keeping "never reported" distinct from zero.

    The old accumulator coerced `None` to 0, so a provider that says nothing
    about cached tokens was indistinguishable from one reporting none -- and
    those are billed identically while meaning different things.
    """
    if previous is None and reported is None:
        return None
    return (previous or 0) + (reported or 0)


class ChatProtocolAgent(AgentAdapter):
    """An adapter that drives a chat model through a JSON action protocol.

    Subclasses implement :meth:`complete` and nothing else.
    """

    name = "chat"

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        #: Alternating user/assistant turns, oldest first. Actually appended to,
        #: which is the fix -- see the module docstring.
        self._messages: list[dict[str, str]] = []
        self._usage = UsageMetadata()
        self._model_ms = 0.0

    # -- provider hook -------------------------------------------------------

    @abstractmethod
    def complete(
        self, system: str, history: list[dict[str, str]], user: str
    ) -> tuple[str, dict[str, Any] | None]:
        """One turn against the provider. Returns (text, usage-or-None).

        Raise on a transport or protocol failure; :meth:`act` turns that into a
        recorded adapter error rather than a crashed run, because "the endpoint
        was down" and "the agent failed the task" both score zero and mean
        entirely different things.
        """

    # -- the loop ------------------------------------------------------------

    def system_prompt(self) -> str:
        """The tool catalogue the model is given.

        It once listed tool *names* and nothing else, so a model had to invent
        the arguments to `patch_file` -- and the harness recorded the invention
        as the agent's error, which made part of the score a measurement of this
        prompt. It also listed every *registered* tool rather than the ones the
        task allows, so a model was told about tools whose every call the
        executor denies.
        """
        from tooltrace.agents.tool_schemas import render_prompt_block

        catalogue = render_prompt_block(
            self._ctx.allowed_tools or None, self._ctx.tool_descriptions or None
        )
        files = ", ".join(self._ctx.workspace_files) or "(empty)"
        return SYSTEM_PROMPT.format(
            tools=catalogue,
            objective=self._ctx.objective,
            description=self._ctx.description or "(none)",
            files=files,
        )

    def record_usage(self, reported: dict[str, Any] | None) -> None:
        if not reported:
            return
        previous = self._usage.tokens or TokenUsage()
        self._usage.tokens = TokenUsage(
            prompt_tokens=add_counts(previous.prompt_tokens, reported.get("prompt_tokens")),
            completion_tokens=add_counts(
                previous.completion_tokens, reported.get("completion_tokens")
            ),
            total_tokens=add_counts(previous.total_tokens, reported.get("total_tokens")),
            cached_prompt_tokens=add_counts(
                previous.cached_prompt_tokens, reported.get("cached_prompt_tokens")
            ),
            cache_write_tokens=add_counts(
                previous.cache_write_tokens, reported.get("cache_write_tokens")
            ),
            reasoning_tokens=add_counts(
                previous.reasoning_tokens, reported.get("reasoning_tokens")
            ),
        )

    def _decide(self, user_content: str) -> dict[str, object]:
        start = time.perf_counter()
        text, usage = self.complete(self.system_prompt(), list(self._messages), user_content)
        self._model_ms += (time.perf_counter() - start) * 1000.0
        self.record_usage(usage)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"model returned non-JSON content: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("model JSON must be an object")

        # Appended only after the turn parsed. A malformed reply is not part of
        # the conversation the next turn should be reasoning from.
        self._messages.append({"role": "user", "content": user_content})
        self._messages.append({"role": "assistant", "content": text})
        if len(self._messages) > HISTORY_TURNS * 2:
            self._messages = self._messages[-HISTORY_TURNS * 2 :]
        return parsed

    def act(self, step: int, observations: list[str]) -> AgentAction:
        observation_text = (
            chr(10).join(f"Observation {i + 1}: {o}" for i, o in enumerate(observations[-5:]))
            or "No observations yet."
        )
        try:
            decision = self._decide(observation_text)
        except Exception as exc:
            return AgentAction(kind="finish", message=f"adapter error: {exc}")

        action = str(decision.get("action", ""))
        if action == "tool":
            tool = decision.get("tool")
            args = decision.get("args", {})
            if not isinstance(tool, str) or not isinstance(args, dict):
                return AgentAction(kind="finish", message="malformed tool action from model")
            return AgentAction(kind="tool", tool=tool, args=args)
        return AgentAction(kind="finish", message=str(decision.get("message", "")))

    def finalize(self) -> AgentOutcome:
        said = [m["content"] for m in self._messages if m["role"] == "assistant"]
        return AgentOutcome(
            messages=said,
            final_output=said[-1] if said else "",
            finish_reason="finished",
            usage=UsageMetadata(tokens=self._usage.tokens, model_time_ms=self._model_ms or None),
        )
