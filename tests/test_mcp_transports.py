"""stdio, HTTP, and HTTP that streams -- the same protocol three ways.

The client spoke stdio and only stdio, which covers a server you start yourself
and nothing else. Every hosted MCP server is reached over HTTP, so a conformance
report that could not reach one was a report about the easy half of the
ecosystem.

The transports are worth testing separately because exactly one thing differs:
framing. A streamed reply may carry a progress notification *before* the result,
and a client that reads the first `data:` frame and calls it the answer works
against every server that does not stream and breaks against every one that
does. The fixture sends that notification deliberately -- a fixture that only
ever sends the happy shape proves the client handles the happy shape.
"""

from __future__ import annotations

import json

import pytest
from tooltrace.agents.mcp import MCPClient, MCPStartupError, fake_server_command
from tooltrace.agents.mcp_conformance import report
from tooltrace.agents.mcp_http_fixture import FixtureServer
from tooltrace.agents.mcp_transports import (
    HttpTransport,
    StdioTransport,
    TransportError,
    _messages_from_event_stream,
)

# --- the same checks over each transport ------------------------------------


def test_stdio_still_works() -> None:
    with MCPClient(fake_server_command()) as client:
        assert client.transport_name == "stdio"
        assert [t["name"] for t in client.list_tools()] == ["echo"]


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_the_full_conformance_suite_passes_over_http(mode: str) -> None:
    with FixtureServer(mode) as server:
        result = report(url=server.url)
    assert result["ok"] is True, result["required_failures"]
    assert result["transport"] == "http"


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_a_tool_call_round_trips_over_http(mode: str) -> None:
    with FixtureServer(mode) as server, MCPClient(url=server.url) as client:
        record = client.call_tool("echo", {"text": "hello"})
    assert record["status"] == "ok"
    assert record["result"]["content"][0]["text"] == "hello"


def test_the_transport_name_reflects_what_the_server_did() -> None:
    """Streaming is the server's choice per response, not a client setting.

    Reporting the configured transport rather than the observed one would say
    `http` for a server that streams every reply.
    """
    with FixtureServer("json") as server, MCPClient(url=server.url) as client:
        client.list_tools()
        assert client.transport_name == "http"
    with FixtureServer("sse") as server, MCPClient(url=server.url) as client:
        client.list_tools()
        assert client.transport_name == "streamable-http"


def test_an_error_response_arrives_over_http_as_an_error() -> None:
    with FixtureServer("sse") as server, MCPClient(url=server.url) as client:
        record = client.call_tool("not_a_real_tool")
    assert record["status"] == "error"


# --- event-stream framing ---------------------------------------------------


def test_a_notification_before_the_result_is_skipped_past() -> None:
    """The bug this transport exists to avoid.

    A client that took the first frame would return a progress notification for
    every call, and the result would never be seen.
    """
    with FixtureServer("sse") as server, MCPClient(url=server.url) as client:
        tools = client.list_tools()
    assert tools, "the result was lost behind the notification that preceded it"


def test_a_data_field_split_across_lines_is_rejoined() -> None:
    """SSE joins consecutive `data:` lines with a newline.

    Reading only the first line yields invalid JSON, and the failure looks like
    a malformed server rather than a malformed reader.
    """
    body = 'data: {"jsonrpc": "2.0",\ndata:  "id": 7, "result": {}}\n\n'
    messages = _messages_from_event_stream(body)
    assert messages == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


def test_several_frames_come_back_in_order() -> None:
    body = "".join(f"data: {json.dumps({'id': i})}\n\n" for i in range(3))
    assert [m["id"] for m in _messages_from_event_stream(body)] == [0, 1, 2]


def test_an_unparseable_frame_is_dropped_rather_than_raising() -> None:
    body = 'data: not json\n\ndata: {"id": 1}\n\n'
    assert _messages_from_event_stream(body) == [{"id": 1}]


# --- failure modes ----------------------------------------------------------


def test_an_unreachable_url_is_a_startup_error_not_a_protocol_one() -> None:
    """The distinction `MCPError` could not make before it was split."""
    client = MCPClient(url="http://127.0.0.1:1/mcp")
    with pytest.raises(MCPStartupError):
        client.start()


def test_a_transport_needs_something_to_talk_to() -> None:
    with pytest.raises(TransportError):
        StdioTransport([])
    with pytest.raises(TransportError):
        HttpTransport("")


def test_a_client_with_neither_command_nor_url_is_refused() -> None:
    with pytest.raises(Exception, match="command, url or transport required"):
        MCPClient()


def test_sending_before_start_is_an_error_not_an_assertion() -> None:
    """It used to be a bare `assert`, which vanishes under `python -O`."""
    with pytest.raises(TransportError):
        StdioTransport(["python"]).send({"jsonrpc": "2.0"})


# --- the fixture is a real server, not a mock -------------------------------


def test_the_http_fixture_and_the_stdio_fixture_agree_on_the_tool_list() -> None:
    """Two fixtures that disagree would let the transports drift apart."""
    with MCPClient(fake_server_command()) as stdio_client:
        over_stdio = [t["name"] for t in stdio_client.list_tools()]
    with FixtureServer("json") as server, MCPClient(url=server.url) as http_client:
        over_http = [t["name"] for t in http_client.list_tools()]
    assert over_stdio == over_http


def test_the_fixture_binds_only_to_loopback() -> None:
    with FixtureServer("json") as server:
        assert server.url.startswith("http://127.0.0.1:")


def test_an_unknown_fixture_mode_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        FixtureServer("websocket")


def test_the_version_matrix_runs_over_http() -> None:
    """The transport must not change what the protocol checks can ask."""
    with FixtureServer("sse") as server:
        from tooltrace.agents.mcp_versions import version_matrix

        result = version_matrix(url=server.url)
    assert result["supported"] == ["2024-11-05"]
    assert result["ok"] is True


def test_the_conformance_cli_accepts_a_url(capsys) -> None:
    from tooltrace.cli.main import main

    with FixtureServer("json") as server:
        assert main(["mcp-conformance", "--url", server.url, "--json"]) == 0
    capsys.readouterr()
