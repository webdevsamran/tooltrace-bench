"""Secret sanitization and detection.

Every tool event, trace payload and report passes through :func:`sanitize_text`
before persistence. Detection is pattern-based and intentionally conservative:
when in doubt, redact. Publication checks fail on likely secrets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# (label, compiled pattern). Order matters: more specific patterns first.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{16,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "bearer-token",
        re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}={0,2}"),
    ),
    (
        "basic-auth-url",
        re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/:@]+@[^\s]+", re.IGNORECASE),
    ),
    (
        "credential-assignment",
        re.compile(
            r"""(?i)\b(api[_-]?key|secret|password|passwd|token|credential)s?\b"""
            r"""\s*[:=]\s*["']?[^\s"']{8,}"""
        ),
    ),
    (
        "private-path",
        re.compile(r"""(?i)(?:[A-Za-z]:\\Users\\[^\\\s"']+|/home/[^/\s"']+|/Users/[^/\s"']+)"""),
    ),
]

_REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class SecretFinding:
    label: str
    start: int
    end: int
    preview: str  # first 6 chars only — never the full secret


def find_secrets(text: str) -> list[SecretFinding]:
    """Return likely-secret findings in *text* (never the secret itself)."""
    findings: list[SecretFinding] = []
    for label, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            findings.append(
                SecretFinding(
                    label=label,
                    start=m.start(),
                    end=m.end(),
                    preview=text[m.start() : m.start() + 6],
                )
            )
    return findings


def sanitize_text(text: str) -> str:
    """Redact likely secrets in *text*."""
    out = text
    for _, pattern in _PATTERNS:
        out = pattern.sub(_REDACTED, out)
    return out


def sanitize_obj(obj: Any) -> Any:
    """Recursively sanitize strings inside JSON-like structures."""
    if isinstance(obj, str):
        return sanitize_text(obj)
    if isinstance(obj, dict):
        return {k: sanitize_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_obj(v) for v in obj]
    return obj


def summarize(text: str, limit: int = 200) -> str:
    """Sanitize and truncate text for event summaries."""
    cleaned = " ".join(sanitize_text(text).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def has_likely_secrets(text: str) -> bool:
    return bool(find_secrets(text))
