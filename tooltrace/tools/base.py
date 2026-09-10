"""Tool base classes and context.

Every tool:

- is registered by name in ``tool_registry``;
- declares its parameters as a JSON Schema in ``parameters``;
- receives a :class:`ToolContext` bound to a sandbox workspace;
- returns a :class:`ToolResult`;
- never sees raw secrets in its recorded event (the executor sanitizes).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import jsonschema
from pydantic import BaseModel, Field

from tooltrace.core.exceptions import PolicyViolation

#: Kept here rather than imported from tooltrace.security.canary to avoid a
#: cycle: the security package imports tools, not the other way round.
EGRESS_DIR = ".tooltrace_egress"


class ToolContext(BaseModel):
    """Execution context handed to every tool call."""

    workspace: Path
    network_policy: str = "disabled"
    http_allowlist: list[str] = Field(default_factory=list)
    env_allowlist: list[str] = Field(default_factory=list)
    #: Values planted by a security task whose escape is the thing being
    #: measured, as {id: value}. Carried here so a tool can match them on raw
    #: arguments *before* the executor sanitizes -- the sanitizer redacts
    #: secret-shaped strings, so matching afterwards would find nothing and
    #: every agent would look perfectly secure. Additive and empty by default,
    #: so no existing task or tool is affected.
    canaries: dict[str, str] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}


class ToolResult(BaseModel):
    """Structured result of one tool invocation."""

    ok: bool
    output: str = ""
    error: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


class ToolArgumentError(ValueError):
    """Arguments that the tool's declared schema rejects.

    Distinct from a tool *failure*: the call never reached the tool. An agent
    that calls `read_file` with no `path` has made a different mistake from one
    whose `read_file` hit a missing file, and collapsing the two hides the more
    interesting of them.
    """


@dataclass(frozen=True)
class ArgumentReport:
    """What a tool's schema makes of one set of arguments.

    Two findings, deliberately separated, because they are not equally serious:

    - ``errors`` -- a required argument is missing, or one has the wrong type.
      The call cannot proceed.
    - ``unknown`` -- an argument the schema does not declare. Recorded and
      **not** fatal. A model passing an extra key is sloppy rather than broken,
      and a strict harness would fail runs that a real provider would accept.
      It is still a signal worth counting: an invented parameter is the same
      hallucination as an invented tool, one level down.
    """

    errors: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


class Tool(ABC):
    """Base class for typed tools."""

    name: str = "tool"
    description: str = ""

    #: JSON Schema for this tool's arguments -- an object schema with
    #: ``properties`` and, where it matters, ``required``.
    #:
    #: Empty means *undeclared*, and undeclared means unchecked: a tool from a
    #: plugin that predates this field behaves exactly as it did. That is a
    #: deliberate hole rather than an oversight, and `tooltrace tools` and
    #: `tooltrace doctor` both report a registered tool with no schema, because
    #: "nothing is validated" and "everything passed validation" look identical
    #: from the outside.
    #:
    #: ``additionalProperties`` is intentionally absent: unknown keys are
    #: reported through :class:`ArgumentReport`, not rejected here.
    parameters: ClassVar[dict[str, Any]] = {}

    @abstractmethod
    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        """Execute the tool. Must not raise for expected failures — return
        ``ok=False`` instead. Unexpected exceptions are caught by the
        executor and converted into error results."""

    def check_args(self, args: dict[str, object]) -> ArgumentReport:
        """Grade *args* against :attr:`parameters` without raising.

        The executor calls this so a schema violation becomes a recorded,
        countable outcome rather than a stack trace flattened into a string.
        """
        schema = self.parameters
        if not schema:
            return ArgumentReport()

        validator = jsonschema.Draft202012Validator(schema)
        errors = tuple(
            f"{'/'.join(str(p) for p in error.absolute_path) or 'arguments'}: {error.message}"
            for error in sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
        )
        declared = set(schema.get("properties", {}))
        unknown = tuple(sorted(key for key in args if key not in declared))
        return ArgumentReport(errors=errors, unknown=unknown)

    def validate_args(self, args: dict[str, object]) -> None:
        """Raise :class:`ToolArgumentError` when the declared schema rejects *args*.

        Override this for validity a schema cannot express -- a value that has
        to exist in the workspace, two arguments that are mutually exclusive.
        An override should call ``super().validate_args(args)`` first unless it
        means to replace the schema check entirely.
        """
        report = self.check_args(args)
        if not report.ok:
            raise ToolArgumentError("; ".join(report.errors))


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
    # The egress log is the record of what an agent tried to send. An agent
    # that could rewrite it could erase the evidence of its own exfiltration,
    # so the whole prefix is refused to every path-taking tool.
    if candidate.parts and candidate.parts[0] == EGRESS_DIR:
        raise PolicyViolation(f"{EGRESS_DIR}/ is reserved for the harness: {relative!r}")
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
