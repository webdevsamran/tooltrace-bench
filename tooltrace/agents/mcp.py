"""MCP (Model Context Protocol) client support and conformance fixtures
(features 51, 52).

The client speaks JSON-RPC 2.0 over stdio to any MCP server process, captures
a tool inventory, and records every call for trace capture. Conformance
fixtures exercise initialize -> tools/list -> tools/call semantics against a
server independently of any agent model; an in-process fake server is provided
for deterministic tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


class MCPError(RuntimeError):
    pass


class MCPStartupError(MCPError):
    """The server process could not be started, or closed the stream."""


class MCPProtocolError(MCPError):
    """The server answered with a JSON-RPC error.

    Separate from :class:`MCPStartupError` because a caller has to tell "the
    server refused this request" from "there is no server". Both used to be one
    exception whose message a caller had to substring-match, and matching
    `"error"` in it classified `[WinError 2] the system cannot find the file`
    as a polite refusal.
    """


class MCPClient:
    """Minimal MCP client: initialize, tools/list, tools/call over stdio."""

    def __init__(self, command: list[str], protocol_version: str = "2024-11-05") -> None:
        if not command:
            raise MCPError("command required")
        self._command = command
        self._protocol_version = protocol_version
        self._proc: subprocess.Popen[bytes] | None = None
        self._next_id = 1
        self.call_log: list[dict[str, Any]] = []

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Spawn the server process and perform the initialize handshake."""
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise MCPStartupError(f"failed to start MCP server {self._command}: {exc}") from exc
        result = self._request(
            "initialize",
            {
                "protocolVersion": self._protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "tooltrace-bench", "version": "1.0"},
            },
        )
        self._notify("notifications/initialized", {})
        return result

    def stop(self) -> None:
        if self._proc is not None:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            finally:
                self._proc = None

    def __enter__(self) -> MCPClient:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    # -- JSON-RPC ------------------------------------------------------------

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        data = json.dumps(payload).encode("utf-8")
        self._proc.stdin.write(data + b"\x0a")
        self._proc.stdin.flush()

    def _recv(self) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        line = self._proc.stdout.readline()
        if not line:
            raise MCPStartupError("MCP server closed the stream")
        message: dict[str, Any] = json.loads(line.decode("utf-8"))
        return message

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        while True:
            msg = self._recv()
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise MCPProtocolError(f"{method} failed: {msg['error']}")
                result: dict[str, Any] = msg.get("result", {})
                return result

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # -- MCP operations --------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {})
        return list(result.get("tools", []))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {"tool": name, "arguments": arguments or {}}
        try:
            result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
            record["status"] = "ok"
            record["result"] = result
        except MCPError as exc:
            record["status"] = "error"
            record["error"] = str(exc)[:300]
        self.call_log.append(record)
        return record


# ---------------------------------------------------------------------------
# In-process fake server for deterministic tests / CI-safe fixtures
# ---------------------------------------------------------------------------


# The bundled fixture, and the default target of `tooltrace mcp-conformance`.
#
# It used to crash on three malformed inputs -- `json.loads` was unguarded, and
# `tools/call` reached straight into `msg["params"]["name"]` without checking
# that `params` was a mapping or that `name` was there. `agents/mcp_fuzz.py`
# found all three the first time it ran, against this file.
#
# That mattered more than a fixture bug usually would: this is what
# `mcp-conformance` checks against when nobody names a server, so it is the
# example this project holds up as a *conforming* one. A reference server that
# dies on a truncated line is a poor thing to point at.
#
# Every entry point is now guarded, and every guard answers with a JSON-RPC
# error rather than staying silent, because a client cannot distinguish silence
# from a hang.
FAKE_SERVER_SCRIPT = r"""
import json, sys

TOOLS = {
    "echo": {"name": "echo", "description": "echo text back",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
}

def send(obj):
    sys.stdout.write(json.dumps(obj) + "\x0a"); sys.stdout.flush()

def fail(msg_id, code, message):
    send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue

    # A parse error is an error, not a crash and not silence. -32700 is the
    # JSON-RPC code for exactly this, and the id is null because there is no
    # parsed request to take one from.
    try:
        msg = json.loads(line)
    except ValueError:
        fail(None, -32700, "parse error")
        continue

    if not isinstance(msg, dict):
        fail(None, -32600, "invalid request: not an object")
        continue
    if "id" not in msg:
        continue

    msg_id = msg["id"]
    method = msg.get("method")
    # A non-string method cannot name anything; dispatching on it would be a
    # type confusion rather than a lookup.
    if not isinstance(method, str):
        fail(msg_id, -32600, "invalid request: method must be a string")
        continue

    params = msg.get("params", {})
    if not isinstance(params, dict):
        fail(msg_id, -32602, "invalid params: must be an object")
        continue

    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg_id, "result":
              {"protocolVersion": "2024-11-05",
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "fake-mcp", "version": "0.1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": list(TOOLS.values())}})
    elif method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            # The request that must never succeed: calling an unnamed tool.
            fail(msg_id, -32602, "invalid params: name is required and must be a string")
            continue
        args = params.get("arguments")
        args = args if isinstance(args, dict) else {}
        if name == "echo":
            send({"jsonrpc": "2.0", "id": msg_id, "result":
                  {"content": [{"type": "text", "text": str(args.get("text", ""))}]}})
        else:
            fail(msg_id, -32602, "unknown tool " + name)
    else:
        fail(msg_id, -32601, "unknown method " + method)
"""


def fake_server_command() -> list[str]:
    """Command running the bundled fake MCP server (deterministic fixture)."""
    return [sys.executable, "-c", FAKE_SERVER_SCRIPT]


# ---------------------------------------------------------------------------
# Conformance check (feature 52)
# ---------------------------------------------------------------------------


def conformance_check(command: list[str]) -> dict[str, Any]:
    """Exercise initialize/tools-list/echo-call semantics against an MCP
    server. Independent of any agent model. Returns pass/fail per fixture."""
    checks: dict[str, bool] = {}
    problems: list[str] = []
    client = MCPClient(command)
    try:
        info = client.start()
        checks["initialize"] = bool(info.get("serverInfo"))
        tools = client.list_tools()
        checks["tools_list"] = isinstance(tools, list) and len(tools) > 0
        echo = next((t for t in tools if t.get("name") == "echo"), None)
        if echo is not None:
            out = client.call_tool("echo", {"text": "ping"})
            text = ""
            content = out.get("result", {}).get("content", [])
            if content and isinstance(content[0], dict):
                text = str(content[0].get("text", ""))
            checks["tools_call_echo"] = out.get("status") == "ok" and text == "ping"
        else:
            checks["tools_call_echo"] = False
            problems.append("fixture tool 'echo' missing from inventory")
        unknown = client.call_tool("no_such_tool", {})
        checks["unknown_tool_errors"] = unknown.get("status") == "error"
    except Exception as exc:
        problems.append(f"conformance exception: {exc}")
        checks.setdefault("initialize", False)
    finally:
        client.stop()
    return {
        "ok": all(checks.values()) and not problems,
        "checks": checks,
        "problems": problems,
        "call_log": client.call_log,
    }
