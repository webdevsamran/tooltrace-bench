"""Anthropic Messages API adapter.

Not reachable through `openai_compat`, which is why this exists rather than a
preset. The Messages API differs from `/chat/completions` in four ways that all
break a client written for the other one:

- the system prompt is a **top-level field**, not a message with `role: system`;
- `max_tokens` is **required**, and a request without it is rejected outright;
- the version is an **HTTP header** (`anthropic-version`), not a path segment;
- the reply is a list of typed content blocks, so the text is
  `content[i].text` for the blocks whose `type` is `text` -- and a response that
  begins with a `thinking` block puts nothing useful at index 0.

Token usage is reported as `input_tokens` / `output_tokens` with cache counts at
the top level rather than nested, which is what `extract_usage` already handles.

Config:
    {
      "model": "claude-sonnet-5",
      "api_key_env": "ANTHROPIC_API_KEY",
      "max_tokens": 2048,
      "base_url": "https://api.anthropic.com",   # optional
      "timeout_seconds": 60
    }

The key is read from the environment by name. This package never stores a
credential and never writes one into a config file or a bundle.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from tooltrace.agents.chat_base import ChatProtocolAgent
from tooltrace.agents.local_backends import extract_usage

DEFAULT_BASE_URL = "https://api.anthropic.com"

#: Pinned rather than "latest". A benchmark whose results move because a
#: provider shipped a default change is measuring the provider's release
#: schedule.
API_VERSION = "2023-06-01"

#: Required by the API. A default here is a guess, but no default at all makes
#: every first run fail on a field the user has no way to know about.
DEFAULT_MAX_TOKENS = 2048


class AnthropicAgent(ChatProtocolAgent):
    name = "anthropic"

    def complete(
        self, system: str, history: list[dict[str, str]], user: str
    ) -> tuple[str, dict[str, Any] | None]:
        env_name = str(self.config.get("api_key_env", "ANTHROPIC_API_KEY"))
        api_key = os.environ.get(env_name)
        if not api_key:
            raise ValueError(
                f"no API key in ${env_name}. The anthropic adapter reads the key from the "
                "environment by name and never stores one"
            )
        base_url = str(self.config.get("base_url", DEFAULT_BASE_URL)).rstrip("/")
        model = str(self.config.get("model", "claude-sonnet-5"))
        timeout = float(self.config.get("timeout_seconds", 60))  # type: ignore[arg-type]

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": int(str(self.config.get("max_tokens", DEFAULT_MAX_TOKENS))),
            "temperature": float(self.config.get("temperature", 0.0)),  # type: ignore[arg-type]
            # Top-level, not a message. A `role: system` entry here is rejected.
            "system": system,
            "messages": [*history, {"role": "user", "content": user}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": API_VERSION,
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/v1/messages", json=payload, headers=headers)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        raw_usage = data.get("usage")
        usage = extract_usage(raw_usage) if isinstance(raw_usage, dict) else None
        return _text_of(data), usage


def _text_of(data: dict[str, Any]) -> str:
    """Join every `text` block, skipping the ones that are not text.

    Taking `content[0]` works until the model returns a `thinking` block first,
    at which point every reply parses as non-JSON and the agent looks broken.
    """
    blocks = data.get("content")
    if not isinstance(blocks, list):
        raise ValueError("Anthropic response carried no content blocks")
    text = "".join(
        str(block.get("text", ""))
        for block in blocks
        if isinstance(block, dict) and block.get("type") == "text"
    )
    if not text:
        kinds = sorted({str(b.get("type")) for b in blocks if isinstance(b, dict)})
        raise ValueError(f"Anthropic response had no text block (types: {kinds})")
    return text
