"""Local model servers, without three adapters that would do the same thing.

Ollama, llama.cpp's server, LM Studio, vLLM and SGLang all expose an
OpenAI-compatible `/chat/completions`, and `openai_compat` already drives it.
Writing five adapter classes that each POST the same body to the same path would
be duplication presented as coverage — five names in `tooltrace agents` and no
new capability behind any of them.

What is actually missing is the knowledge a user otherwise has to acquire the
hard way: which port each server listens on, what it calls a model, and which of
them is running right now. That is what this module holds.

`detect_running()` probes **localhost only**, on the ports these servers
document. It is the one place in this project that opens a socket by default, so
it is worth being explicit: nothing leaves the machine, there is no registry
lookup, and a probe that finds nothing reports nothing rather than guessing.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any


#: Presets, not adapters. Each is a config for `openai_compat`.
@dataclass(frozen=True)
class Backend:
    name: str
    port: int
    base_url: str
    #: What this server calls the model field. All of them accept `model`; the
    #: difference is what a *valid value* looks like, which is what trips people.
    model_hint: str
    note: str
    #: Whether the server usually needs an API key. Local servers mostly do not,
    #: and telling someone to set one they do not need is its own kind of wrong.
    needs_key: bool = False


BACKENDS: dict[str, Backend] = {
    "ollama": Backend(
        name="ollama",
        port=11434,
        base_url="http://localhost:11434/v1",
        model_hint="qwen2.5-coder:7b",
        note=(
            "Model names carry a tag (`:7b`, `:latest`). A name without one is "
            "usually accepted and resolves to `:latest`, which makes a run "
            "unreproducible -- pin the tag."
        ),
    ),
    "llama_cpp": Backend(
        name="llama_cpp",
        port=8080,
        base_url="http://localhost:8080/v1",
        model_hint="(whatever `-m` loaded; the field is ignored)",
        note=(
            "llama-server serves one model and ignores the `model` field entirely, "
            "so the recorded model name comes from your config rather than from the "
            "server. Record what you actually loaded."
        ),
    ),
    "lm_studio": Backend(
        name="lm_studio",
        port=1234,
        base_url="http://localhost:1234/v1",
        model_hint="lmstudio-community/Qwen2.5-Coder-7B-Instruct-GGUF",
        note="Model names are the full repo path shown in the LM Studio server log.",
    ),
    "vllm": Backend(
        name="vllm",
        port=8000,
        base_url="http://localhost:8000/v1",
        model_hint="Qwen/Qwen2.5-Coder-7B-Instruct",
        note=(
            "The model name must match what vLLM was served with, exactly. "
            "Quantization, tensor parallelism and prefix caching are server-side "
            "flags: they change results and this harness cannot see them, so "
            "declare them in the agent config to get them into the bundle."
        ),
    ),
    "sglang": Backend(
        name="sglang",
        port=30000,
        base_url="http://localhost:30000/v1",
        model_hint="Qwen/Qwen2.5-Coder-7B-Instruct",
        note="Same as vLLM: server-side flags are invisible here unless declared.",
    ),
}


def config_for(
    backend: str,
    *,
    model: str = "",
    api_key_env: str = "",
    quantization: str = "",
    engine_version: str = "",
) -> dict[str, Any]:
    """An `openai_compat` config for a named local backend.

    The `backend`, `quantization` and `engine_version` fields are carried into
    the bundle's declared-inference block. None of them is detectable from
    inside the harness -- a model served over an OpenAI-compatible endpoint could
    be anything, quantized any way -- so they are recorded as declarations and
    labelled as such by `telemetry/hardware.py`.
    """
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; known: {sorted(BACKENDS)}")
    spec = BACKENDS[backend]
    config: dict[str, Any] = {
        "base_url": spec.base_url,
        "model": model or spec.model_hint,
        "temperature": 0.0,
        # Declared, never detected. See `telemetry/hardware.declared_backend`.
        "backend": backend,
    }
    if api_key_env:
        config["api_key_env"] = api_key_env
    if quantization:
        config["quantization"] = quantization
    if engine_version:
        config["engine_version"] = engine_version
    return config


def _port_open(port: int, *, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """Is something listening? Localhost only, and a short timeout.

    A closed port is the common case and must not cost a second each time.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def detect_running() -> list[dict[str, Any]]:
    """Which known local servers are listening, on this machine only.

    An open port is evidence that *something* is listening there, which is not
    the same as that server being the thing listening. The result says so rather
    than claiming a positive identification it has not made.
    """
    found = []
    for spec in BACKENDS.values():
        if _port_open(spec.port):
            found.append(
                {
                    "backend": spec.name,
                    "port": spec.port,
                    "base_url": spec.base_url,
                    "model_hint": spec.model_hint,
                    "note": spec.note,
                    # The honest limit of a port probe.
                    "evidence": (
                        f"something is listening on localhost:{spec.port}, which is "
                        f"{spec.name}'s documented port. This is not a positive "
                        "identification of the server."
                    ),
                }
            )
    return found


def describe() -> dict[str, Any]:
    """Everything known, plus what is up right now."""
    running = {row["backend"] for row in detect_running()}
    return {
        "backends": [
            {
                "backend": spec.name,
                "port": spec.port,
                "base_url": spec.base_url,
                "model_hint": spec.model_hint,
                "needs_key": spec.needs_key,
                "note": spec.note,
                "listening": spec.name in running,
            }
            for spec in BACKENDS.values()
        ],
        "listening": sorted(running),
        "statement": (
            "All of these speak the OpenAI chat API, so they run through the "
            "`openai_compat` adapter rather than five adapters that would send the same "
            "request. Detection probes localhost only; nothing leaves this machine."
        ),
    }


# --- reading what a provider actually reports -------------------------------


def extract_usage(usage: dict[str, Any]) -> dict[str, int | None]:
    """Pull every token dimension a response reports, across provider shapes.

    `TokenUsage` grew `cached_prompt_tokens`, `cache_write_tokens` and
    `reasoning_tokens`, and `PriceTable` learned to bill them -- and nothing
    populated them, so a cache-heavy run was still costed at the full input rate.
    That is this project's recurring defect, committed here by the same change
    that added the fields.

    Providers disagree on where these live:

    - OpenAI-style nests them: `prompt_tokens_details.cached_tokens`,
      `completion_tokens_details.reasoning_tokens`.
    - Anthropic-style puts them at the top level:
      `cache_read_input_tokens`, `cache_creation_input_tokens`.
    - Most local servers report none of it, which is why every field here can be
      `None` rather than defaulting to zero. Zero cached tokens and *no
      information about caching* would be billed identically and mean different
      things.
    """

    def as_int(value: Any) -> int | None:
        return int(value) if isinstance(value, int) and value >= 0 else None

    prompt_details = usage.get("prompt_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = usage.get("completion_tokens_details")
    completion_details = completion_details if isinstance(completion_details, dict) else {}

    cached = as_int(prompt_details.get("cached_tokens"))
    if cached is None:
        cached = as_int(usage.get("cache_read_input_tokens"))

    cache_write = as_int(usage.get("cache_creation_input_tokens"))
    if cache_write is None:
        cache_write = as_int(prompt_details.get("cache_creation_tokens"))

    reasoning = as_int(completion_details.get("reasoning_tokens"))
    if reasoning is None:
        reasoning = as_int(usage.get("reasoning_tokens"))

    return {
        "prompt_tokens": as_int(usage.get("prompt_tokens")),
        "completion_tokens": as_int(usage.get("completion_tokens")),
        "total_tokens": as_int(usage.get("total_tokens")),
        "cached_prompt_tokens": cached,
        "cache_write_tokens": cache_write,
        "reasoning_tokens": reasoning,
    }
