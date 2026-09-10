"""OpenAI-compatible HTTP agent adapter (suitable for local endpoints).

Config:
    {
      "base_url": "http://localhost:8000/v1",   # any OpenAI-compatible server
      "model": "local-model",
      "api_key_env": "LOCAL_LLM_API_KEY",       # optional; read from env only
      "temperature": 0.0,
      "timeout_seconds": 60
    }

The adapter implements a minimal tool-use loop: each turn it asks the model
for a JSON action ``{"action": "tool", "tool": ..., "args": {...}}`` or
``{"action": "finish", "message": ...}``. No provider SDK is required — just
HTTP. Token usage is recorded **only when the endpoint reports usage**.
"""

from __future__ import annotations

import json
import os
import time

import httpx

from tooltrace.agents.base import AgentAdapter
from tooltrace.agents.local_backends import extract_usage
from tooltrace.core.models import (
    AgentAction,
    AgentContext,
    AgentOutcome,
    TokenUsage,
    UsageMetadata,
)

SYSTEM_PROMPT = """You are an autonomous coding agent operating inside a sandboxed workspace.

Available tools: {tools}

Respond with EXACTLY one JSON object and nothing else:
{{"action": "tool", "tool": "<tool name>", "args": {{...}}}}
or, when the task is complete:
{{"action": "finish", "message": "<summary>"}}

Objective: {objective}
Task description: {description}
Workspace files: {files}
"""


def _add(previous: int | None, reported: int | None) -> int | None:
    """Accumulate across turns, keeping "never reported" distinct from zero.

    The old accumulator coerced `None` to 0, so a provider that says nothing
    about cached tokens was indistinguishable from one reporting none -- and
    those are billed identically while meaning different things.
    """
    if previous is None and reported is None:
        return None
    return (previous or 0) + (reported or 0)


class OpenAICompatAgent(AgentAdapter):
    name = "openai_compat"

    def initialize(self, ctx: AgentContext) -> None:
        self._ctx = ctx
        self._messages: list[dict[str, str]] = []
        self._usage = UsageMetadata()
        self._model_ms = 0.0

    def _api_key(self) -> str | None:
        env_name = str(self.config.get("api_key_env", ""))
        return os.environ.get(env_name) if env_name else None

    def _chat(self, user_content: str) -> dict[str, object]:
        base_url = str(self.config.get("base_url", "")).rstrip("/")
        if not base_url:
            raise ValueError("openai_compat agent requires config 'base_url'")
        model = str(self.config.get("model", "local-model"))
        timeout = float(self.config.get("timeout_seconds", 60))  # type: ignore[arg-type]
        headers = {"Content-Type": "application/json"}
        api_key = self._api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model,
            "temperature": float(self.config.get("temperature", 0.0)),  # type: ignore[arg-type]
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                *self._messages,
                {"role": "user", "content": user_content},
            ],
        }
        start = time.perf_counter()
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        self._model_ms += (time.perf_counter() - start) * 1000.0
        resp.raise_for_status()
        data: dict[str, object] = resp.json()
        usage = data.get("usage")
        if isinstance(usage, dict):
            # Every dimension the provider reports, across the shapes they use.
            # `TokenUsage` grew cached / cache-write / reasoning fields and
            # `PriceTable` learned to bill them, and nothing populated them --
            # so a cache-heavy run was still costed at the full input rate.
            reported = extract_usage(usage)
            prev = self._usage.tokens or TokenUsage()
            self._usage.tokens = TokenUsage(
                prompt_tokens=_add(prev.prompt_tokens, reported["prompt_tokens"]),
                completion_tokens=_add(prev.completion_tokens, reported["completion_tokens"]),
                total_tokens=_add(prev.total_tokens, reported["total_tokens"]),
                cached_prompt_tokens=_add(
                    prev.cached_prompt_tokens, reported["cached_prompt_tokens"]
                ),
                cache_write_tokens=_add(prev.cache_write_tokens, reported["cache_write_tokens"]),
                reasoning_tokens=_add(prev.reasoning_tokens, reported["reasoning_tokens"]),
            )
        raw_choices = data.get("choices")
        choices = raw_choices if isinstance(raw_choices, list) else []
        if not choices:
            raise ValueError("endpoint returned no choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {})
        message = message if isinstance(message, dict) else {}
        content = message.get("content", "{}")
        try:
            parsed = json.loads(str(content))
        except json.JSONDecodeError as exc:
            raise ValueError(f"model returned non-JSON content: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("model JSON must be an object")
        return parsed

    def _system_prompt(self) -> str:
        from tooltrace.core.registry import tool_registry

        names = ", ".join(tool_registry.names())
        files = ", ".join(self._ctx.workspace_files) or "(empty)"
        return SYSTEM_PROMPT.format(
            tools=names,
            objective=self._ctx.objective,
            description=self._ctx.description or "(none)",
            files=files,
        )

    def act(self, step: int, observations: list[str]) -> AgentAction:
        observation_text = (
            chr(10).join(f"Observation {i + 1}: {o}" for i, o in enumerate(observations[-5:]))
            or "No observations yet."
        )
        try:
            decision = self._chat(observation_text)
        except Exception as exc:
            return AgentAction(kind="finish", message=f"adapter error: {exc}")
        action = str(decision.get("action", ""))
        if action == "tool":
            tool = decision.get("tool")
            args = decision.get("args", {})
            if not isinstance(tool, str) or not isinstance(args, dict):
                return AgentAction(
                    kind="finish",
                    message="malformed tool action from model",
                )
            return AgentAction(kind="tool", tool=tool, args=args)
        return AgentAction(kind="finish", message=str(decision.get("message", "")))

    def finalize(self) -> AgentOutcome:
        return AgentOutcome(
            messages=[m["content"] for m in self._messages],
            final_output="",
            finish_reason="finished",
            usage=UsageMetadata(
                tokens=self._usage.tokens,
                model_time_ms=self._model_ms or None,
            ),
        )
