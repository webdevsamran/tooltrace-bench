"""Adapter interoperability layer (features 48, 54, 55, 56, 57, 58, 59).

- capability negotiation between harness and agent adapters;
- provider/model metadata normalization (revision, endpoint mode, sampling,
  reasoning effort);
- deterministic retry/backoff policy represented in traces;
- rate-limit telemetry excluding benchmark-side waiting from model-compute time
  when distinguishable;
- pre-flight health/doctor checks;
- secret-safe credential resolution (values never persisted);
- cost accounting strictly from user-supplied timestamped price tables.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Capability negotiation (feature 54)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterCapabilities:
    streaming: bool = False
    tool_calls: bool = True
    images: bool = False
    audio: bool = False
    json_mode: bool = False
    reasoning_metadata: bool = False
    usage_accounting: bool = True


HARNESS_REQUIRED_CAPABILITIES = ("tool_calls", "usage_accounting")


def negotiate(
    adapter_caps: AdapterCapabilities,
    required: tuple[str, ...] = HARNESS_REQUIRED_CAPABILITIES,
) -> dict[str, Any]:
    """Negotiate harness requirements against adapter capabilities.

    Returns {"ok": bool, "missing": [...], "granted": {...}}. Never mutates
    either side; callers must refuse to run when ok is False.
    """
    granted = {
        "streaming": adapter_caps.streaming,
        "tool_calls": adapter_caps.tool_calls,
        "images": adapter_caps.images,
        "audio": adapter_caps.audio,
        "json_mode": adapter_caps.json_mode,
        "reasoning_metadata": adapter_caps.reasoning_metadata,
        "usage_accounting": adapter_caps.usage_accounting,
    }
    missing = [cap for cap in required if not granted.get(cap)]
    return {"ok": not missing, "missing": missing, "granted": granted}


# ---------------------------------------------------------------------------
# Provider/model metadata normalization (feature 48)
# ---------------------------------------------------------------------------


class ModelMetadata(BaseModel):
    provider: str
    model_id: str
    revision: str | None = None  # snapshot/version when exposed
    endpoint_mode: str = "api"  # api | local-server | subprocess
    sampling: dict[str, float] = Field(default_factory=dict)  # temperature etc.
    reasoning_effort: str | None = None
    base_url_host: str | None = None  # host only; never full URLs with keys

    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


def normalize_model_metadata(raw: Mapping[str, Any]) -> ModelMetadata:
    """Normalize heterogeneous provider payloads into ModelMetadata."""
    sampling = {}
    for key in ("temperature", "top_p", "top_k", "presence_penalty", "frequency_penalty"):
        if raw.get(key) is not None:
            sampling[key] = float(raw[key])
    base_url = raw.get("base_url") or ""
    host = None
    if base_url:
        try:
            from urllib.parse import urlsplit

            host = urlsplit(str(base_url)).hostname
        except ValueError:
            host = None
    return ModelMetadata(
        provider=str(raw.get("provider", "unknown")),
        model_id=str(raw.get("model") or raw.get("model_id") or "unknown"),
        revision=raw.get("revision") or raw.get("model_version"),
        endpoint_mode=str(raw.get("endpoint_mode", "api")),
        sampling=sampling,
        reasoning_effort=raw.get("reasoning_effort"),
        base_url_host=host,
    )


# ---------------------------------------------------------------------------
# Deterministic retry/backoff (feature 55) + rate-limit telemetry (feature 56)
# ---------------------------------------------------------------------------


class RetryPolicy:
    """Deterministic exponential backoff for safe transient failures only."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_s: float = 0.05,
        factor: float = 2.0,
        retry_on: tuple[str, ...] = ("timeout", "rate_limited", "transient"),
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay_s = base_delay_s
        self.factor = factor
        self.retry_on = retry_on

    def delay_for(self, attempt: int) -> float:
        """Deterministic backoff after ``attempt`` (0-based) failure."""
        return self.base_delay_s * (self.factor**attempt)

    def should_retry(self, error_kind: str, attempt: int) -> bool:
        return error_kind in self.retry_on and attempt + 1 < self.max_attempts


def run_with_retries(
    operation: Callable[[], Any],
    classify_error: Callable[[Exception], str],
    policy: RetryPolicy | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute with retries; returns attempts log + result/error.

    The returned record is designed to be embedded in traces so retries are
    always visible in scores (feature 55).
    """
    policy = policy or RetryPolicy()
    attempts: list[dict[str, Any]] = []
    waited_s = 0.0
    for attempt in range(policy.max_attempts):
        started = time.perf_counter()
        try:
            value = operation()
            attempts.append(
                {
                    "attempt": attempt,
                    "ok": True,
                    "duration_s": round(time.perf_counter() - started, 6),
                }
            )
            return {"result": value, "attempts": attempts, "benchmark_waited_s": round(waited_s, 6)}
        except Exception as exc:
            kind = classify_error(exc)
            attempts.append(
                {
                    "attempt": attempt,
                    "ok": False,
                    "error_kind": kind,
                    "error": str(exc)[:200],
                    "duration_s": round(time.perf_counter() - started, 6),
                }
            )
            if policy.should_retry(kind, attempt):
                delay = policy.delay_for(attempt)
                waited_s += delay
                sleeper(delay)
                continue
            raise
    raise RuntimeError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------------------
# Health / doctor checks (feature 57)
# ---------------------------------------------------------------------------


def adapter_health_check(
    name: str,
    probes: Mapping[str, Callable[[], bool]],
) -> dict[str, Any]:
    """Run cheap probes (config present, endpoint reachable, auth readable)
    BEFORE expensive suites start. Returns structured doctor report."""
    report: dict[str, Any] = {"adapter": name, "checks": {}, "healthy": True}
    for probe_name, probe in probes.items():
        try:
            ok = bool(probe())
        except Exception as exc:
            ok = False
            report["checks"][f"{probe_name}_error"] = str(exc)[:200]
        report["checks"][probe_name] = ok
        report["healthy"] = report["healthy"] and ok
    return report


# ---------------------------------------------------------------------------
# Secret-safe credential resolution (feature 58)
# ---------------------------------------------------------------------------


class CredentialResolver:
    """Resolve credentials from environment or a keyfile without ever storing
    values in results/traces. Callers receive opaque handles."""

    def __init__(self, env: Mapping[str, str] | None = None, keyfile: str | None = None) -> None:
        self._env = dict(env if env is not None else os.environ)
        self._keyfile_values: dict[str, str] = {}
        if keyfile and os.path.exists(keyfile):
            try:
                with open(keyfile, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line and "=" in line and not line.startswith("#"):
                            key, _, val = line.partition("=")
                            self._keyfile_values[key.strip()] = val.strip()
            except OSError:
                pass

    def resolve(self, logical_name: str) -> str | None:
        """Return the secret value or None. NEVER log/serialize the value."""
        if logical_name in self._env:
            return self._env[logical_name]
        return self._keyfile_values.get(logical_name)

    def resolve_ref(self, logical_name: str) -> dict[str, Any]:
        """Safe representation for manifests/traces: presence + fingerprint."""
        value = self.resolve(logical_name)
        if value is None:
            return {"name": logical_name, "present": False}
        fp = hashlib.sha256(value.encode()).hexdigest()[:12]
        return {"name": logical_name, "present": True, "sha256_prefix": fp}


# ---------------------------------------------------------------------------
# Cost accounting from explicit price tables (feature 59)
# ---------------------------------------------------------------------------


class PriceEntry(BaseModel):
    input_per_1k: float
    output_per_1k: float
    currency: str = "USD"
    effective_from: str  # ISO date; newest entry <= usage date wins


class PriceTable(BaseModel):
    prices: dict[str, list[PriceEntry]] = Field(default_factory=dict)

    @classmethod
    def load(cls, path_or_json: str) -> PriceTable:
        try:
            data = json.loads(path_or_json)
        except json.JSONDecodeError:
            with open(path_or_json, encoding="utf-8") as fh:
                data = json.load(fh)
        return cls.model_validate(data)

    def _entry_for(self, model: str, at_date: str) -> PriceEntry | None:
        candidates = [e for e in self.prices.get(model, []) if e.effective_from <= at_date]
        return sorted(candidates, key=lambda e: e.effective_from)[-1] if candidates else None

    def compute_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        at_date: str,
        allow_unpriced: bool = False,
    ) -> dict[str, Any]:
        """Cost strictly from the explicit table. Unpriced models raise unless
        allow_unpriced=True (then cost is reported as unknown, never guessed)."""
        entry = self._entry_for(model, at_date)
        if entry is None:
            if allow_unpriced:
                return {"model": model, "cost": None, "currency": None, "priced": False}
            raise KeyError(
                f"no price configured for model {model!r} effective {at_date}; "
                "add it to your price table instead of guessing"
            )
        cost = (input_tokens / 1000.0) * entry.input_per_1k + (
            output_tokens / 1000.0
        ) * entry.output_per_1k
        return {
            "model": model,
            "cost": round(cost, 6),
            "currency": entry.currency,
            "priced": True,
            "price_effective_from": entry.effective_from,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

# ---------------------------------------------------------------------------
# Generic provider-compatible protocol layers (feature 49)
# ---------------------------------------------------------------------------
# Vendor-neutral HTTP protocol specs so any OpenAI-, Anthropic- or
# Gemini-compatible endpoint can be driven without vendor SDKs and without
# hard-coding a preferred provider. These are pure request/response mappers;
# transport is injected by the caller (testable offline).


@dataclass(frozen=True)
class ProviderProtocolSpec:
    name: str
    chat_path: str
    auth_header: str  # format template, e.g. "Bearer {api_key}"
    extra_headers: tuple[tuple[str, str], ...] = ()
    tool_call_style: str = "openai"  # openai | anthropic_content_blocks | gemini_function_calls


OPENAI_COMPAT_SPEC = ProviderProtocolSpec(
    name="openai-compat", chat_path="/v1/chat/completions", auth_header="Bearer {api_key}"
)
ANTHROPIC_COMPAT_SPEC = ProviderProtocolSpec(
    name="anthropic-compat",
    chat_path="/v1/messages",
    auth_header="{api_key}",
    extra_headers=(("anthropic-version", "2023-06-01"),),
    tool_call_style="anthropic_content_blocks",
)
GEMINI_COMPAT_SPEC = ProviderProtocolSpec(
    name="gemini-compat",
    chat_path="/v1beta/models/{model}:generateContent",
    auth_header="{api_key}",
    extra_headers=(("x-goog-api-key", "{api_key}"),),
    tool_call_style="gemini_function_calls",
)

PROTOCOL_SPECS = {
    s.name: s for s in (OPENAI_COMPAT_SPEC, ANTHROPIC_COMPAT_SPEC, GEMINI_COMPAT_SPEC)
}


def build_provider_request(
    spec: ProviderProtocolSpec,
    *,
    model: str,
    system: str,
    user: str,
    tools: list[dict[str, Any]] | None = None,
    api_key_ref: str = "",
) -> dict[str, Any]:
    """Build a normalized request payload + headers for *spec*.

    Returns {"path": str, "headers": {...}, "body": {...}}. The API key is
    referenced by env-var name only; its value is resolved by CredentialResolver
    at send time and never appears here.
    """
    headers: dict[str, str] = {}
    for k, v in spec.extra_headers:
        headers[k] = v.replace("{api_key}", api_key_ref)
    if spec.name == "anthropic-compat":
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if tools:
            body["tools"] = [
                {"name": t.get("name", ""), "description": t.get("description", ""),
                 "input_schema": t.get("parameters", {})}
                for t in tools
            ]
        path = spec.chat_path
    elif spec.name == "gemini-compat":
        body = {
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": system}]},
        }
        if tools:
            body["tools"] = [{"functionDeclarations": [
                {"name": t.get("name", ""), "description": t.get("description", ""),
                 "parameters": t.get("parameters", {})}
                for t in tools
            ]}]
        path = spec.chat_path.replace("{model}", model)
    else:  # openai-compat default
        body = {
            "model": model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.get("name", ""), "description": t.get("description", ""),
                "parameters": t.get("parameters", {}),
            }} for t in tools]
        path = spec.chat_path
    auth = spec.auth_header.replace("{api_key}", api_key_ref)
    if auth:
        headers["Authorization"] = auth
    return {"path": path, "headers": headers, "body": body}


def parse_provider_tool_call(
    spec: ProviderProtocolSpec, response: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Extract the first tool call from a provider response, normalized to
    {"name": ..., "arguments": {...}} across all three wire styles."""
    try:
        if spec.tool_call_style == "anthropic_content_blocks":
            for block in response["content"]:
                if block.get("type") == "tool_use":
                    return {"name": block["name"], "arguments": dict(block.get("input", {}))}
        elif spec.tool_call_style == "gemini_function_calls":
            parts = response["candidates"][0]["content"]["parts"]
            for part in parts:
                if "functionCall" in part:
                    fc = part["functionCall"]
                    return {"name": fc["name"], "arguments": dict(fc.get("args", {}))}
        else:
            msg = response["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            if calls:
                fn = calls[0]["function"]
                args = fn.get("arguments", "{}")
                parsed = json.loads(args) if isinstance(args, str) else dict(args)
                return {"name": fn["name"], "arguments": parsed}
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None
