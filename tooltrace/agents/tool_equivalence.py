"""Does a tool declared once mean the same thing to four providers?

`tool_schemas.present` renders the registry in OpenAI, Anthropic, MCP and Gemini
shapes. Rendering is not the same as preserving: a wrapper that moves a schema
from ``parameters`` to ``input_schema`` loses nothing, and one that strips the
keywords a provider rejects loses something specific. Both look like success
from the call site.

So this reads each rendering back, compares it to the declaration it came from,
and names what changed. The answer for three of the four dialects is "nothing",
which is worth stating rather than assuming -- and the answer for the fourth is a
list a reader can act on, before a model sends an argument the declaration no
longer permits.

The comparison is on *meaning*, not bytes. A dialect that renames a key is
equivalent; one that drops a constraint is not. That distinction is the whole
value: an equality check would report every dialect as different and tell nobody
anything.
"""

from __future__ import annotations

from typing import Any

from tooltrace.agents.tool_schemas import present, presentations

#: The keys each dialect stores the argument schema under.
SCHEMA_KEY = {
    "openai": ("function", "parameters"),
    "anthropic": ("input_schema",),
    "mcp": ("inputSchema",),
    "gemini": ("parameters",),
}

#: Constraints whose loss changes what a model may legally send. Presence or
#: absence of a `description` does not; presence of `required` does.
MEANING_BEARING = ("type", "required", "enum", "oneOf", "anyOf", "minimum", "maximum", "items")


def _dig(entry: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    node: Any = entry
    for key in path:
        node = node.get(key, {}) if isinstance(node, dict) else {}
    return node if isinstance(node, dict) else {}


def _constraints(schema: dict[str, Any]) -> set[str]:
    """Every meaning-bearing constraint in a schema, as `property.keyword` labels."""
    found: set[str] = set()
    for keyword in MEANING_BEARING:
        if keyword in schema:
            found.add(f".{keyword}")
    for name, spec in (schema.get("properties") or {}).items():
        if not isinstance(spec, dict):
            continue
        for keyword in MEANING_BEARING:
            if keyword in spec:
                found.add(f"{name}.{keyword}")
    for name in schema.get("required") or []:
        found.add(f"{name}.required")
    return found


def equivalence_report(names: list[str] | None = None) -> dict[str, Any]:
    """Compare every dialect's rendering against the declaration it came from."""
    declared = {t.name: t for t in presentations(names)}
    dialects: dict[str, Any] = {}

    for dialect, path in SCHEMA_KEY.items():
        losses: list[dict[str, Any]] = []
        for entry in present(names, dialect):
            name = str(entry.get("name") or _dig(entry, ("function",)).get("name") or "")
            source = declared.get(name)
            if source is None:  # pragma: no cover - names come from the same registry
                continue
            rendered = _dig(entry, path)
            missing = sorted(_constraints(source.parameters) - _constraints(rendered))
            if missing:
                losses.append({"tool": name, "dropped": missing})
        dialects[dialect] = {
            "lossless": not losses,
            "losses": losses,
            "statement": (
                "every declared constraint survives"
                if not losses
                else f"{len(losses)} tool(s) lose a constraint this provider cannot express"
            ),
        }

    lossy = sorted(d for d, r in dialects.items() if not r["lossless"])
    return {
        "tools": len(declared),
        "dialects": dialects,
        "lossy_dialects": lossy,
        # Not a failure. A provider that cannot express a union is a fact about
        # that provider, and reporting it as a defect in this project's tools
        # would be blaming the wrong party.
        "ok": True,
        "statement": (
            f"{len(declared)} tool(s) across {len(dialects)} dialects: "
            + (
                f"{', '.join(lossy)} cannot express every declared constraint; "
                "the rest are lossless."
                if lossy
                else "every dialect preserves every declared constraint."
            )
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["| Dialect | Lossless | What it drops |", "|---|---|---|"]
    for dialect, result in report["dialects"].items():
        if result["lossless"]:
            lines.append(f"| `{dialect}` | yes | -- |")
            continue
        dropped = "; ".join(
            f"`{loss['tool']}`: {', '.join(loss['dropped'])}" for loss in result["losses"][:3]
        )
        lines.append(f"| `{dialect}` | no | {dropped} |")
    lines += ["", report["statement"]]
    if report["lossy_dialects"]:
        lines += [
            "",
            "A provider that cannot express a constraint is a fact about that provider, "
            "not a defect in the tool. It matters because the narrowed declaration is what "
            "the model reads: it will not send what the declaration no longer permits.",
        ]
    return "\n".join(lines) + "\n"
