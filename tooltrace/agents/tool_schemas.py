"""Present the tool registry to a model, in whichever dialect it speaks.

Every provider asks for the same three things -- a name, a description and a
JSON Schema for the arguments -- and every provider wraps them differently.
OpenAI nests them under ``function``; Anthropic puts the schema in
``input_schema``; MCP calls it ``inputSchema``; Gemini uses
``functionDeclarations`` and rejects the JSON Schema keywords it does not know.
One presenter, four wrappers, so a tool is declared once.

There is a fifth dialect, ``prompt``, for adapters that drive a model through a
JSON protocol in the system prompt rather than a native tool-calling API. It
exists because this repository's own adapter needed it: it was listing tool
*names*, with no descriptions and no argument schemas at all, so every model
running against it had to guess what `patch_file` takes. Guessing wrong is
recorded as the agent's mistake, which made the harness the source of the
measurement it was reporting.

The same function is also what makes tool-poisoning measurable. A description
is the one field an agent reads and a schema cannot constrain, so a poisoned
description travels through here untouched -- which is the point: the presenter
is where a task can substitute one deliberately.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tooltrace.core.registry import tool_registry

DIALECTS = ("openai", "anthropic", "mcp", "gemini", "prompt")

#: JSON Schema keywords the Gemini function-calling schema does not accept.
#: Passing one through is a request error rather than a warning, so they are
#: dropped and the drop is reported rather than being silent.
_GEMINI_UNSUPPORTED = frozenset(
    {"additionalProperties", "oneOf", "anyOf", "allOf", "not", "$schema", "$ref", "const"}
)

_EMPTY_OBJECT: dict[str, Any] = {"type": "object", "properties": {}}


@dataclass(frozen=True)
class ToolPresentation:
    """One tool as a model will see it."""

    name: str
    description: str
    parameters: dict[str, Any]
    #: True when the tool declares no schema. Carried rather than hidden: a
    #: model handed `{"type": "object", "properties": {}}` cannot tell "this
    #: tool takes nothing" from "nobody wrote the schema down", and neither can
    #: a reader of the report.
    undeclared: bool
    #: True when the task replaced this tool's own description. Carried so a
    #: report can say the agent was *attacked* rather than only that it
    #: misbehaved -- an agent that leaks a credential because a poisoned tool
    #: told it to has failed differently from one that did it unprompted.
    substituted_description: bool = False


def presentations(
    names: list[str] | None = None,
    descriptions: Mapping[str, str] | None = None,
) -> list[ToolPresentation]:
    """Look up *names* in the registry, or present everything registered.

    *descriptions* substitutes the text an agent is shown for a tool, without
    touching the tool. That is the tool-poisoning surface: a description is the
    one field an agent reads and a schema cannot constrain, so an agent that
    reads it as an instruction rather than as documentation will follow whatever
    a compromised MCP server wrote there. A task plants one here and the
    substitution is recorded on the presentation, so a trace shows that the
    agent was attacked rather than merely that it misbehaved.

    An unregistered name is skipped rather than raising. The call site is
    usually a task's ``allowed_tools``, and `tooltrace lint` already fails a
    task that names a tool which does not exist -- raising here would turn a
    lint finding into a crash mid-run.
    """
    wanted = list(names) if names else list(tool_registry.names())
    overrides = dict(descriptions or {})
    out: list[ToolPresentation] = []
    for name in wanted:
        if not tool_registry.has(name):
            continue
        tool_cls = tool_registry.get(name)
        tool = tool_cls() if isinstance(tool_cls, type) else tool_cls
        schema = getattr(tool, "parameters", {}) or {}
        own = (getattr(tool, "description", "") or "").strip()
        substituted = name in overrides
        out.append(
            ToolPresentation(
                name=getattr(tool, "name", name) or name,
                description=overrides[name].strip() if substituted else own,
                parameters=copy.deepcopy(schema) if schema else copy.deepcopy(_EMPTY_OBJECT),
                undeclared=not schema,
                substituted_description=substituted,
            )
        )
    return out


def _collapse_union(schema: dict[str, Any]) -> dict[str, Any]:
    """Narrow a ``oneOf``/``anyOf`` to its first branch, and say so in the text.

    Dropping the keyword alone leaves a property with a description and no
    ``type``, which Gemini rejects -- so a tool that declares an honest union
    (`git` takes a list of arguments *or* one string) would make the whole
    request fail. The first branch is adopted and the description says the
    declaration is narrower than the tool, because a model that reads only the
    schema would otherwise be told something untrue about what it may send.
    """
    branches = schema.get("oneOf") or schema.get("anyOf") or []
    first = next((b for b in branches if isinstance(b, dict)), None)
    if first is None:
        return schema
    narrowed = {k: v for k, v in schema.items() if k not in {"oneOf", "anyOf"}}
    for key in ("type", "items", "enum", "format"):
        if key in first:
            narrowed[key] = first[key]
    note = "This provider's schema cannot express the alternatives; send the declared type."
    narrowed["description"] = f"{narrowed.get('description', '').strip()} {note}".strip()
    return narrowed


def _strip_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    if "oneOf" in schema or "anyOf" in schema:
        schema = _collapse_union(schema)
    cleaned: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _GEMINI_UNSUPPORTED:
            continue
        if key == "properties" and isinstance(value, dict):
            cleaned[key] = {
                k: _strip_for_gemini(v) if isinstance(v, dict) else v for k, v in value.items()
            }
        elif isinstance(value, dict):
            cleaned[key] = _strip_for_gemini(value)
        else:
            cleaned[key] = value
    # Gemini requires a type on every schema node, and rejects the request
    # rather than warning.
    if "type" not in cleaned:
        cleaned["type"] = "object" if "properties" in cleaned else "string"
    return cleaned


def present(
    names: list[str] | None = None,
    dialect: str = "openai",
    descriptions: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Render the registry in one provider's tool-declaration shape."""
    if dialect not in DIALECTS or dialect == "prompt":
        raise ValueError(
            f"unknown tool dialect {dialect!r}; expected one of "
            f"{', '.join(d for d in DIALECTS if d != 'prompt')} "
            "(use render_prompt_block for the prompt dialect)"
        )

    rendered: list[dict[str, Any]] = []
    for tool in presentations(names, descriptions):
        if dialect == "openai":
            rendered.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
            )
        elif dialect == "anthropic":
            rendered.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
            )
        elif dialect == "mcp":
            rendered.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
            )
        else:  # gemini
            rendered.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": _strip_for_gemini(tool.parameters),
                }
            )
    return rendered


def render_prompt_block(
    names: list[str] | None = None,
    descriptions: Mapping[str, str] | None = None,
) -> str:
    """A compact text catalogue for adapters that have no native tool API.

    Names alone are not a tool catalogue. A model told only that `patch_file`
    exists has to invent its arguments, and this harness then records the
    invention as the agent's error -- so the number it reports is partly a
    measurement of its own prompt.
    """
    lines: list[str] = []
    for tool in presentations(names, descriptions):
        properties = tool.parameters.get("properties", {})
        required = set(tool.parameters.get("required", []))
        if not properties:
            argument_text = "no arguments declared" if tool.undeclared else "no arguments"
        else:
            parts = []
            for key, spec in properties.items():
                kind = spec.get("type", "any") if isinstance(spec, dict) else "any"
                if isinstance(spec, dict) and "enum" in spec:
                    kind = "|".join(str(v) for v in spec["enum"])
                parts.append(f"{key}:{kind}" + ("" if key in required else "?"))
            argument_text = ", ".join(parts)
        description = f" -- {tool.description}" if tool.description else ""
        lines.append(f"- {tool.name}({argument_text}){description}")
    return "\n".join(lines) or "(no tools available)"


def coverage() -> dict[str, Any]:
    """Which registered tools declare a schema, and which do not.

    Reported rather than asserted. A tool with no schema is not broken -- it is
    unchecked, and "nothing is validated" looks exactly like "everything passed
    validation" unless something says which one is true.
    """
    all_tools = presentations()
    undeclared = sorted(t.name for t in all_tools if t.undeclared)
    return {
        "tools": len(all_tools),
        "declared": len(all_tools) - len(undeclared),
        "undeclared": undeclared,
        "statement": (
            f"{len(all_tools) - len(undeclared)} of {len(all_tools)} registered tools declare "
            "an argument schema"
            + (
                f"; {', '.join(undeclared)} do not, so their arguments are unchecked."
                if undeclared
                else "."
            )
        ),
    }
