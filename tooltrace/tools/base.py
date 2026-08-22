"""Tool base classes and context.

Every tool:

- is registered by name in ``tool_registry``;
- receives a :class:`ToolContext` bound to a sandbox workspace;
- returns a :class:`ToolResult`;
- never sees raw secrets in its recorded event (the executor sanitizes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field

from tooltrace.core.exceptions import PolicyViolation


class ToolContext(BaseModel):
    """Execution context handed to every tool call."""

    workspace: Path
    network_policy: str = "disabled"
    http_allowlist: list[str] = Field(default_factory=list)
    env_allowlist: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


class ToolResult(BaseModel):
    """Structured result of one tool invocation."""

    ok: bool
    output: str = ""
    error: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


class Tool(ABC):
    """Base class for typed tools."""

    name: str = "tool"
    description: str = ""

    @abstractmethod
    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        """Execute the tool. Must not raise for expected failures — return
        ``ok=False`` instead. Unexpected exceptions are caught by the
        executor and converted into error results."""

    def validate_args(self, args: dict[str, object]) -> None:  # noqa: B027
        """Optional hook for argument validation; raise ValueError for bad arguments."""


def resolve_in_workspace(workspace: Path, relative: object) -> Path:
    """Resolve *relative* inside *workspace*, refusing any escape.

    Raises :class:`PolicyViolation` on absolute paths, ``..`` traversal,
    drive changes or symlink escapes.
    """
    if not isinstance(relative, str) or not relative.strip():
        raise PolicyViolation("Path argument must be a non-empty string")
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        raise PolicyViolation(f"Absolute paths are not allowed: {relative!r}")
    resolved_root = workspace.resolve()
    target = (resolved_root / candidate).resolve()
    if resolved_root != target and resolved_root not in target.parents:
        raise PolicyViolation(f"Path escapes the workspace boundary: {relative!r}")
    return target


def summarize_args(args: dict[str, object], limit: int = 160) -> str:
    parts = []
    for key, value in args.items():
        text = value if isinstance(value, str) else repr(value)
        if len(text) > 60:
            text = text[:57] + "..."
        parts.append(f"{key}={text}")
    summary = ", ".join(parts)
    return summary[:limit]
