"""Declared tool parameters, and presenting them to four providers.

`Tool.validate_args` was an empty hook that no tool overrode, so a tool's
arguments were whatever the tool happened to read out of a dict. Every tool now
declares a JSON Schema and the executor grades arguments against it before the
call, which separates two mistakes that used to be one number: an agent calling
`read_file` with no `path`, and `read_file` failing to find the file.

The presentation layer exists for the other half of that problem. This project's
own adapter was listing tool *names* in the system prompt -- no descriptions, no
argument schemas -- so a model had to invent the arguments to `patch_file`, and
the harness then scored the invention as the agent's error. Part of the number
it reported was a measurement of its own prompt.
"""

from __future__ import annotations

import pytest
from tooltrace.agents.tool_schemas import (
    DIALECTS,
    coverage,
    present,
    presentations,
    render_prompt_block,
)
from tooltrace.core.registry import tool_registry
from tooltrace.tools.base import ArgumentReport, Tool, ToolArgumentError, ToolContext, ToolResult

# --- every shipped tool declares its arguments ------------------------------


def test_every_registered_tool_declares_a_schema() -> None:
    report = coverage()
    assert report["undeclared"] == [], (
        f"these tools take arguments nothing checks: {report['undeclared']}"
    )
    assert report["declared"] == report["tools"]


def test_a_declared_schema_is_an_object_with_properties() -> None:
    for tool in presentations():
        assert tool.parameters.get("type") == "object", tool.name
        assert "properties" in tool.parameters, tool.name


def test_required_arguments_are_named_in_properties() -> None:
    """A `required` entry with no property is a schema that rejects everything."""
    for tool in presentations():
        declared = set(tool.parameters.get("properties", {}))
        for name in tool.parameters.get("required", []):
            assert name in declared, f"{tool.name} requires undeclared {name!r}"


# --- grading arguments ------------------------------------------------------


def instantiate(name: str) -> Tool:
    cls = tool_registry.get(name)
    return cls() if isinstance(cls, type) else cls


def test_a_missing_required_argument_is_an_error() -> None:
    report = instantiate("read_file").check_args({})
    assert not report.ok
    assert any("path" in message for message in report.errors)


def test_a_wrong_type_is_an_error() -> None:
    report = instantiate("write_file").check_args({"path": "a.txt", "content": 5})
    assert not report.ok


def test_a_valid_call_produces_no_findings() -> None:
    report = instantiate("write_file").check_args({"path": "a.txt", "content": "hi"})
    assert report.ok
    assert report.unknown == ()


def test_an_undeclared_argument_is_reported_and_not_fatal() -> None:
    """A model passing an extra key is sloppy rather than broken.

    Failing the call would fail runs that a real provider would accept, so the
    finding is recorded and the call proceeds. It is still a hallucination one
    level below an invented tool, which is why it is counted at all.
    """
    report = instantiate("read_file").check_args({"path": "a.txt", "encoding": "utf-8"})
    assert report.ok
    assert report.unknown == ("encoding",)


def test_validate_args_raises_on_a_schema_error() -> None:
    with pytest.raises(ToolArgumentError):
        instantiate("calculator").validate_args({})


def test_an_undeclared_tool_is_unchecked_rather_than_rejected() -> None:
    """A plugin tool written before this field behaves exactly as it did."""

    class LegacyTool(Tool):
        name = "legacy"

        def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
            return ToolResult(ok=True)

    report = LegacyTool().check_args({"anything": 1})
    assert report == ArgumentReport()
    assert report.ok


# --- presenting to providers ------------------------------------------------


def test_openai_wraps_the_schema_under_function() -> None:
    entry = next(t for t in present(["read_file"], "openai"))
    assert entry["type"] == "function"
    assert entry["function"]["parameters"]["required"] == ["path"]


def test_anthropic_calls_it_input_schema() -> None:
    entry = present(["read_file"], "anthropic")[0]
    assert "input_schema" in entry and "parameters" not in entry


def test_mcp_calls_it_input_schema_in_camel_case() -> None:
    entry = present(["read_file"], "mcp")[0]
    assert "inputSchema" in entry


def test_gemini_drops_the_keywords_it_rejects() -> None:
    """A request error is a poor way to find out that `oneOf` is unsupported."""
    entry = present(["git"], "gemini")[0]
    args = entry["parameters"]["properties"]["args"]
    assert "oneOf" not in args
    assert args["type"] == "string"


def test_narrowing_for_gemini_says_so_in_the_description() -> None:
    """`git` really does accept a list; the declaration no longer can."""
    args = present(["git"], "gemini")[0]["parameters"]["properties"]["args"]
    assert "cannot express the alternatives" in args["description"]


def test_every_dialect_names_every_requested_tool() -> None:
    for dialect in DIALECTS:
        if dialect == "prompt":
            continue
        rendered = present(None, dialect)
        assert len(rendered) == len(presentations())


def test_an_unknown_dialect_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown tool dialect"):
        present(None, "cohere")


def test_the_prompt_dialect_is_not_a_json_shape() -> None:
    with pytest.raises(ValueError):
        present(None, "prompt")


# --- the prompt catalogue ---------------------------------------------------


def test_the_prompt_block_names_arguments_not_just_tools() -> None:
    block = render_prompt_block(["patch_file"])
    assert "path:string" in block
    assert "search:string" in block
    assert "replace_all:boolean?" in block, "optional arguments must be marked optional"


def test_the_prompt_block_carries_the_description() -> None:
    assert "Read a text file" in render_prompt_block(["read_file"])


def test_an_unregistered_name_is_skipped_rather_than_raising() -> None:
    """`tooltrace lint` fails a task naming a missing tool; a run should not crash."""
    assert presentations(["read_file", "definitely_not_a_tool"]) != []
    assert [t.name for t in presentations(["read_file", "definitely_not_a_tool"])] == ["read_file"]


def test_an_empty_selection_presents_everything() -> None:
    assert len(presentations(None)) == len(tool_registry.names())
