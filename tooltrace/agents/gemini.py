"""Google Gemini `generateContent` adapter.

The third wire format, and the one least like the other two:

- messages are `contents`, and the assistant's role is spelled **`model`**, not
  `assistant`. A transcript with `role: assistant` is rejected;
- each turn's text is wrapped in a `parts` list rather than being a string;
- the system prompt is `systemInstruction`, itself shaped like a content entry;
- JSON mode is `generationConfig.responseMimeType`, not `response_format`;
- usage is `usageMetadata` with `promptTokenCount` / `candidatesTokenCount`,
  and the cached count is `cachedContentTokenCount`.

The API key goes in a header rather than the query string. Both are accepted by
the service; a key in a URL ends up in proxy logs, browser history and error
reports, and this package will not put a credential somewhere that leaks by
default.

Config:
    {
      "model": "gemini-2.5-pro",
      "api_key_env": "GEMINI_API_KEY",
      "base_url": "https://generativelanguage.googleapis.com/v1beta",
      "timeout_seconds": 60
    }
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from tooltrace.agents.chat_base import ChatProtocolAgent
from tooltrace.agents.seeds import seed_of

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

#: How this API spells the two roles. `assistant` is rejected outright.
ROLES = {"user": "user", "assistant": "model"}


class GeminiAgent(ChatProtocolAgent):
    name = "gemini"

    def complete(
        self, system: str, history: list[dict[str, str]], user: str
    ) -> tuple[str, dict[str, Any] | None]:
        env_name = str(self.config.get("api_key_env", "GEMINI_API_KEY"))
        api_key = os.environ.get(env_name)
        if not api_key:
            raise ValueError(
                f"no API key in ${env_name}. The gemini adapter reads the key from the "
                "environment by name and never stores one"
            )
        base_url = str(self.config.get("base_url", DEFAULT_BASE_URL)).rstrip("/")
        model = str(self.config.get("model", "gemini-2.5-pro"))
        timeout = float(self.config.get("timeout_seconds", 60))  # type: ignore[arg-type]

        contents = [
            {"role": ROLES.get(turn["role"], "user"), "parts": [{"text": turn["content"]}]}
            for turn in history
        ]
        contents.append({"role": "user", "parts": [{"text": user}]})

        generation: dict[str, Any] = {
            "temperature": float(self.config.get("temperature", 0.0)),  # type: ignore[arg-type]
            "responseMimeType": "application/json",
        }
        seed = seed_of(self.config)
        if seed is not None:
            generation["seed"] = seed

        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": generation,
        }
        # In a header, not the query string: a key in a URL ends up in proxy
        # logs, browser history and error reports.
        headers = {"content-type": "application/json", "x-goog-api-key": api_key}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{base_url}/models/{model}:generateContent", json=payload, headers=headers
            )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return _text_of(data), _usage_of(data)


def _text_of(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        # `promptFeedback.blockReason` is how a refusal arrives: there are no
        # candidates at all. Saying so beats "no candidates", which reads as a
        # transport failure.
        feedback = data.get("promptFeedback")
        reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
        raise ValueError(f"Gemini returned no candidates (blockReason: {reason or 'none given'})")
    first = candidates[0] if isinstance(candidates[0], dict) else {}
    content = first.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list):
        raise ValueError(
            f"Gemini candidate carried no parts (finishReason: {first.get('finishReason')})"
        )
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
    if not text:
        raise ValueError("Gemini candidate carried no text")
    return text


def _usage_of(data: dict[str, Any]) -> dict[str, Any] | None:
    """`usageMetadata`, translated into the dimensions `TokenUsage` records.

    A provider that reports nothing must stay distinguishable from one
    reporting zero, so a missing field stays `None` rather than becoming 0.
    """
    raw = data.get("usageMetadata")
    if not isinstance(raw, dict):
        return None
    return {
        "prompt_tokens": raw.get("promptTokenCount"),
        "completion_tokens": raw.get("candidatesTokenCount"),
        "total_tokens": raw.get("totalTokenCount"),
        "cached_prompt_tokens": raw.get("cachedContentTokenCount"),
        "cache_write_tokens": None,
        "reasoning_tokens": raw.get("thoughtsTokenCount"),
    }
