"""OpenAI-compatible HTTP agent adapter (suitable for local endpoints).

Config:
    {
      "base_url": "http://localhost:8000/v1",   # any OpenAI-compatible server
      "model": "local-model",
      "api_key_env": "LOCAL_LLM_API_KEY",       # optional; read from env only
      "temperature": 0.0,
      "timeout_seconds": 60
    }

The loop -- system prompt, tool catalogue, conversation history, and the JSON
action protocol -- lives in `chat_base`, shared with the Anthropic and Gemini
adapters. Only the request and the reply shape are here. Three copies of the
loop would drift silently, and a comparison between two models would quietly
become a comparison between two prompts.

No provider SDK is required, just HTTP. Token usage is recorded **only when the
endpoint reports it**.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from tooltrace.agents.chat_base import ChatProtocolAgent, add_counts
from tooltrace.agents.local_backends import extract_usage
from tooltrace.agents.seeds import seed_of

#: Re-exported: `local_backends` and the tests both reach for this, and moving
#: it to `chat_base` without a name here would break them for no reason.
_add = add_counts

SYSTEM_PROMPT_NOTE = "see tooltrace.agents.chat_base.SYSTEM_PROMPT"


class OpenAICompatAgent(ChatProtocolAgent):
    name = "openai_compat"
    #: `image_url` blocks carrying a data: URI; see agents/vision.py.
    dialect = "openai"

    def _api_key(self) -> str | None:
        env_name = str(self.config.get("api_key_env", ""))
        return os.environ.get(env_name) if env_name else None

    def complete(
        self, system: str, history: list[dict[str, str]], user: str | list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any] | None]:
        base_url = str(self.config.get("base_url", "")).rstrip("/")
        if not base_url:
            raise ValueError("openai_compat agent requires config 'base_url'")
        model = str(self.config.get("model", "local-model"))
        timeout = float(self.config.get("timeout_seconds", 60))  # type: ignore[arg-type]
        headers = {"Content-Type": "application/json"}
        api_key = self._api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload: dict[str, Any] = {
            "model": model,
            "temperature": float(self.config.get("temperature", 0.0)),  # type: ignore[arg-type]
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                *history,
                {"role": "user", "content": user},
            ],
        }
        # Sent only when set. An unconditional `"seed": None` is rejected by some
        # OpenAI-compatible servers, which would make configuring nothing worse
        # than configuring something.
        seed = seed_of(self.config)
        if seed is not None:
            payload["seed"] = seed

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        raw_usage = data.get("usage")
        # Every dimension the provider reports, across the shapes they use.
        # `TokenUsage` grew cached / cache-write / reasoning fields and
        # `PriceTable` learned to bill them, and nothing populated them -- so a
        # cache-heavy run was still costed at the full input rate.
        usage = extract_usage(raw_usage) if isinstance(raw_usage, dict) else None

        raw_choices = data.get("choices")
        choices = raw_choices if isinstance(raw_choices, list) else []
        if not choices:
            raise ValueError("endpoint returned no choices")
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {})
        message = message if isinstance(message, dict) else {}
        return str(message.get("content", "{}")), usage
