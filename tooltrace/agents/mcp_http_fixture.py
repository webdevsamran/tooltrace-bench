"""A bundled MCP server reachable over HTTP, in both reply styles.

The stdio fixture proves a stdio client works. It cannot prove anything about
the HTTP transports, and a transport nothing exercises is a transport nobody
knows is broken -- which is the failure this repository keeps finding in itself.

So the same handshake is served over HTTP here, in two modes:

- ``json`` -- the reply is one `application/json` body. What most servers do.
- ``sse`` -- the reply is `text/event-stream` carrying a progress notification
  *before* the result. Deliberately, because that ordering is the thing a naive
  client gets wrong: read the first `data:` frame, call it the answer, and
  every call returns a notification instead of a result.

It runs in a thread on an ephemeral port and is only for tests and `doctor`.
Nothing here listens on a public interface: the bind address is `127.0.0.1` and
there is no configuration to change it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "echo text back",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
        },
    }
]

SESSION_ID = "tooltrace-fixture-session"


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, one reply out, or None for a notification.

    Shared by both reply styles so the two modes differ only in framing. Two
    copies of the dispatch would let the transports drift, and the whole point
    of the fixture is that they do not.
    """
    if "id" not in message:
        return None
    msg_id = message["id"]
    method = message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp-http", "version": "0.1"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name = (params or {}).get("name")
        if not isinstance(name, str):
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": "invalid params: name is required"},
            }
        if name != "echo":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32602, "message": f"unknown tool {name}"},
            }
        arguments = (params or {}).get("arguments")
        text = (arguments or {}).get("text", "") if isinstance(arguments, dict) else ""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": [{"type": "text", "text": str(text)}]},
        }
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"unknown method {method}"},
    }


class _Handler(BaseHTTPRequestHandler):
    mode = "json"

    # `do_POST` is BaseHTTPRequestHandler's spelling; the name is the dispatch.
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        try:
            message = json.loads(raw) if raw else {}
        except ValueError:
            self._send_json(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            )
            return
        if not isinstance(message, dict):
            self._send_json(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "invalid request"},
                }
            )
            return

        reply = handle(message)
        if reply is None:
            # A notification. 202 with no body, which a client must not read as
            # a failed request.
            self.send_response(202)
            self.send_header("mcp-session-id", SESSION_ID)
            self.end_headers()
            return

        if self.mode == "sse":
            self._send_event_stream(reply)
        else:
            self._send_json(reply)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("mcp-session-id", SESSION_ID)
        self.end_headers()
        self.wfile.write(body)

    def _send_event_stream(self, payload: dict[str, Any]) -> None:
        """The result, preceded by a notification the client must skip past."""
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {"progress": 1, "total": 1},
        }
        frames = "".join(f"data: {json.dumps(message)}\n\n" for message in (notification, payload))
        body = frames.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(body)))
        self.send_header("mcp-session-id", SESSION_ID)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        """Silence. The default writes every request to stderr."""


class FixtureServer:
    """A bundled MCP server on localhost, started and stopped by a caller."""

    def __init__(self, mode: str = "json") -> None:
        if mode not in {"json", "sse"}:
            raise ValueError(f"unknown mode {mode!r}; expected 'json' or 'sse'")
        handler = type("_ModeHandler", (_Handler,), {"mode": mode})
        # Port 0: the OS picks a free one. A fixed port makes two test runs on
        # one machine collide, and the collision looks like a broken server.
        self._server = HTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self.mode = mode

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        # `server_address` is typed as accepting bytes for the host, and an
        # f-string on bytes silently produces `b'127.0.0.1'`.
        text = host.decode() if isinstance(host, bytes) else str(host)
        return f"http://{text}:{port}/mcp"

    def __enter__(self) -> FixtureServer:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
