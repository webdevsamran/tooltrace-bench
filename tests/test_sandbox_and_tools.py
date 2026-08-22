"""Sandbox boundaries, tool behavior, and sanitization."""

from __future__ import annotations

import pytest
import tooltrace.tools  # noqa: F401 - registers tools
from tooltrace.core.exceptions import PolicyViolation
from tooltrace.core.registry import tool_registry
from tooltrace.sandbox import TempWorkspaceSandbox
from tooltrace.tools.base import ToolContext, resolve_in_workspace


def ctx_for(ws) -> ToolContext:
    return ToolContext(workspace=ws)


def test_boundary_rejects_traversal(tmp_path) -> None:
    for bad in ("../x", "a/../../b", str(tmp_path / "abs.txt")):
        with pytest.raises(PolicyViolation):
            resolve_in_workspace(tmp_path, bad)


def test_boundary_accepts_inside(tmp_path) -> None:
    p = resolve_in_workspace(tmp_path, "sub/dir/file.txt")
    assert str(p).startswith(str(tmp_path.resolve()))


def test_sandbox_cleanup(task) -> None:
    with TempWorkspaceSandbox() as sb:
        ws = sb.start(task)
        assert (ws / "notes.txt").is_file()
    assert not ws.exists()


def test_read_write_patch_files(workspace) -> None:
    read = tool_registry.get("read_file")()
    write = tool_registry.get("write_file")()
    patch = tool_registry.get("patch_file")()
    r = read.run({"path": "notes.txt"}, ctx_for(workspace))
    assert r.ok and "FOO" in r.output
    w = write.run({"path": "new.txt", "content": "hi"}, ctx_for(workspace))
    assert w.ok and (workspace / "new.txt").read_text(encoding="utf-8") == "hi"
    p = patch.run({"path": "notes.txt", "search": "FOO", "replace": "BAR"}, ctx_for(workspace))
    assert p.ok and "BAR" in (workspace / "notes.txt").read_text(encoding="utf-8")


def test_patch_missing_search_fails(workspace) -> None:
    patch = tool_registry.get("patch_file")()
    r = patch.run({"path": "notes.txt", "search": "ZZZ", "replace": "Y"}, ctx_for(workspace))
    assert not r.ok


def test_shell_denied_outside_commands(workspace) -> None:
    shell = tool_registry.get("shell")()
    r = shell.run({"command": "echo hi"}, ctx_for(workspace))
    assert r.ok


def test_calculator(workspace) -> None:
    calc = tool_registry.get("calculator")()
    r = calc.run({"expression": "2+3*4"}, ctx_for(workspace))
    assert r.ok and r.data.get("value") == 14


def test_list_directory_and_search(workspace) -> None:
    ls = tool_registry.get("list_directory")()
    search = tool_registry.get("search_text")()
    assert ls.run({"path": "."}, ctx_for(workspace)).ok
    s = search.run({"pattern": "FOO", "path": "."}, ctx_for(workspace))
    assert s.ok and "notes.txt" in s.output


def test_http_denied_by_default(workspace) -> None:
    http = tool_registry.get("http")()
    r = http.run({"url": "https://example.com"}, ctx_for(workspace))
    assert not r.ok


def test_executor_records_sanitized_events(workspace) -> None:
    from tooltrace.tools.executor import ToolExecutor

    events: list[object] = []
    ex = ToolExecutor(ctx_for(workspace), ["read_file"], emit_event=events.append)
    result = ex.execute("read_file", {"path": "notes.txt"})
    assert result.ok
    # one request event + one result event per call
    assert len(events) == 2
    req, res = events
    assert req.type == "tool_request" and req.payload["tool"] == "read_file"
    assert res.type == "tool_result" and res.payload["status"] == "ok"


def test_executor_denies_disallowed_tool(workspace) -> None:
    from tooltrace.tools.executor import ToolExecutor

    ex = ToolExecutor(ctx_for(workspace), [], emit_event=lambda e: None)
    result = ex.execute("shell", {"command": "echo hi"})
    assert not result.ok


def test_sanitize_secrets() -> None:
    from tooltrace.security.sanitize import sanitize_text

    # deliberately dummy values (contain "dummy" so the repo secret scan allows them)
    text = "key=sk-dummyabcdefghijklmnopqrst token=Bearer dummyabcdefghijklmnopqrstuvwxyz123456"
    cleaned = sanitize_text(text)
    assert "sk-dummyabcdefghij" not in cleaned
    assert "dummyabcdefghijklmnopqrstuvwxyz123456" not in cleaned
