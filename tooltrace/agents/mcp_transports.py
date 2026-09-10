"""How the JSON-RPC gets to the server: stdio, HTTP, or HTTP that streams.

The client here spoke stdio and only stdio, which covers a local server started
as a subprocess and nothing else. Every hosted MCP server -- which is most of
the ones a team does not run itself -- is reached over HTTP, and a conformance
report that cannot reach them is a report about the easy half of the ecosystem.

Three transports, one wire format. The JSON-RPC is identical in all three; what
differs is framing:

- **stdio** -- one JSON object per line, on the process's stdin and stdout.
  Ordering is the stream's ordering, and a reply is whatever comes back next
  with a matching id.
- **HTTP** -- one POST per request, the reply in the body. The simplest case
  and the one most servers implement first.
- **Streamable HTTP** -- the same POST, but the server may answer
  `text/event-stream` and send several messages before the one you asked for.
  A client that reads the first `data:` line and stops will work against every
  server that does not use this, and break against the ones that do.

That last case is the reason this file exists rather than a single `httpx.post`.
The content type is the server's choice, made per response, so a client has to
handle both on every call rather than deciding once at configuration time.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Protocol

import httpx

#: How long to wait for one HTTP reply. A hosted server doing real work behind
#: a tool call can be slow; a false "unreachable" is worse than a slow check.
HTTP_TIMEOUT = 30.0

JSON_CONTENT = "application/json"
EVENT_STREAM = "text/event-stream"


class TransportError(RuntimeError):
    """The message could not be delivered or no reply came back.

    Distinct from a JSON-RPC error response, which is the server answering.
    """


class Transport(Protocol):
    """What `MCPClient` needs from a way of moving messages."""

    def send(self, payload: dict[str, Any]) -> None: ...

    def recv(self) -> dict[str, Any]: ...

    def close(self) -> None: ...

    @property
    def name(self) -> str: ...


class StdioTransport:
    """One JSON object per line, over a subprocess's stdin and stdout."""

    def __init__(self, command: list[str]) -> None:
        if not command:
            raise TransportError("command required")
        self._command = command
        self._proc: subprocess.Popen[bytes] | None = None

    @property
    def name(self) -> str:
        return "stdio"

    def start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise TransportError(f"failed to start MCP server {self._command}: {exc}") from exc

    def send(self, payload: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise TransportError("transport is not started")
        self._proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\x0a")
        self._proc.stdin.flush()

    def recv(self) -> dict[str, Any]:
        if self._proc is None or self._proc.stdout is None:
            raise TransportError("transport is not started")
        line = self._proc.stdout.readline()
        if not line:
            raise TransportError("MCP server closed the stream")
        message: dict[str, Any] = json.loads(line.decode("utf-8"))
        return message

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:  # pragma: no cover - best-effort teardown
            self._proc.kill()
        finally:
            self._proc = None


def _messages_from_event_stream(body: str) -> list[dict[str, Any]]:
    """Every JSON message in an SSE body, in order.

    A `data:` field can be split across consecutive lines, which the spec joins
    with a newline. Reading only the first line of a multi-line frame yields
    invalid JSON, and the failure looks like a malformed server rather than a
    malformed reader.
    """
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        data_lines.clear()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            messages.append(parsed)

    for line in body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif not line.strip():
            flush()
    flush()
    return messages


class HttpTransport:
    """One POST per request; the reply may be JSON or an event stream.

    Replies are queued rather than returned directly, because a streamed
    response can carry progress notifications before the result. `MCPClient`
    reads until it sees its own id, which is the same thing it does over stdio
    -- so the client needs no knowledge of which transport it is holding.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None) -> None:
        if not url:
            raise TransportError("url required")
        self._url = url
        self._headers = {
            "content-type": JSON_CONTENT,
            # Both, deliberately. The server chooses per response, and a client
            # that accepts only one is telling it to fail on the other.
            "accept": f"{JSON_CONTENT}, {EVENT_STREAM}",
            **(headers or {}),
        }
        self._client = httpx.Client(timeout=HTTP_TIMEOUT)
        self._pending: list[dict[str, Any]] = []
        #: Set from the initialize response. The spec requires later requests to
        #: echo it, and a server that issued one will reject requests without it.
        self._session_id: str | None = None
        self._saw_event_stream = False

    @property
    def name(self) -> str:
        return "streamable-http" if self._saw_event_stream else "http"

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def send(self, payload: dict[str, Any]) -> None:
        headers = dict(self._headers)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        try:
            response = self._client.post(self._url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc

        issued = response.headers.get("mcp-session-id")
        if issued:
            self._session_id = issued

        if response.status_code >= 400:
            raise TransportError(f"HTTP {response.status_code} from {self._url}")

        # A notification legitimately gets 202 with an empty body. Treating that
        # as a protocol failure would make every `notifications/initialized`
        # look like a broken server.
        if response.status_code == 204 or not response.content:
            return

        content_type = response.headers.get("content-type", "")
        if EVENT_STREAM in content_type:
            self._saw_event_stream = True
            self._pending.extend(_messages_from_event_stream(response.text))
            return

        try:
            parsed = response.json()
        except ValueError as exc:
            raise TransportError(f"reply was not JSON: {response.text[:120]}") from exc
        if isinstance(parsed, list):
            self._pending.extend(m for m in parsed if isinstance(m, dict))
        elif isinstance(parsed, dict):
            self._pending.append(parsed)

    def recv(self) -> dict[str, Any]:
        if not self._pending:
            raise TransportError("no reply from the server")
        return self._pending.pop(0)

    def close(self) -> None:
        self._client.close()
