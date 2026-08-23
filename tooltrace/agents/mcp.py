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
            raise MCPError(f"failed to start MCP server {self._command}: {exc}") from exc
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
            raise MCPError("MCP server closed the stream")
        return json.loads(line.decode("utf-8"))

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        req_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        while True:
            msg = self._recv()
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise MCPError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})

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


FAKE_SERVER_SCRIPT = r"""
import json, sys
TOOLS = {
    "echo": {"name": "echo", "description": "echo text back",
             "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
}
def send(obj):
    sys.stdout.write(json.dumps(obj) + "\x0a"); sys.stdout.flush()
initialized = False
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": msg["id"], "result":
              {"protocolVersion": "2024-11-05",
               "capabilities": {"tools": {}},
               "serverInfo": {"name": "fake-mcp", "version": "0.1"}}})
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": list(TOOLS.values())}})
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name == "echo":
            send({"jsonrpc": "2.0", "id": msg["id"], "result":
                  {"content": [{"type": "text", "text": args.get("text", "")}]}})
        else:
            send({"jsonrpc": "2.0", "id": msg["id"], "error":
                  {"code": -32602, "message": f"unknown tool {name}"}})
    else:
        send({"jsonrpc": "2.0", "id": msg["id"], "error":
              {"code": -32601, "message": f"unknown method {method}"}})
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
