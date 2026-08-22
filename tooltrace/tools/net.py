"""Allowlisted HTTP tool.

Network is disabled by default. When a task sets ``network_policy:
allowlisted``, requests are permitted only to hosts explicitly listed in the
task's ``http_allowlist``. Everything else is denied and recorded.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from tooltrace.core.registry import tool_registry
from tooltrace.tools.base import Tool, ToolContext, ToolResult


@tool_registry.register("http")
class HttpTool(Tool):
    name: str = "http"
    description = (
        "Perform an HTTP request against an allowlisted host (GET/POST/PUT/"
        "DELETE). Denied unless the task's network policy allows the host."
    )

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        url = args.get("url")
        method = str(args.get("method", "GET")).upper()
        if not isinstance(url, str) or not url.strip():
            return ToolResult(ok=False, error="url must be a non-empty string")
        if ctx.network_policy != "allowlisted":
            return ToolResult(
                ok=False,
                error="network access denied by task policy (network_policy=disabled)",
                data={"denied": True},
            )
        host = urlparse(url).hostname or ""
        if host not in set(ctx.http_allowlist):
            return ToolResult(
                ok=False,
                error=f"host {host!r} not in task http_allowlist",
                data={"denied": True, "host": host},
            )
        if method not in {"GET", "POST", "PUT", "DELETE", "HEAD"}:
            return ToolResult(ok=False, error=f"unsupported method: {method}")
        body = args.get("body")
        headers = {
            str(k): str(v)
            for k, v in (args.get("headers") or {}).items()  # type: ignore[union-attr]
        }
        try:
            with httpx.Client(timeout=10.0, follow_redirects=False) as client:
                resp = client.request(
                    method,
                    url,
                    json=body if isinstance(body, (dict, list)) else None,
                    content=body if isinstance(body, str) else None,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            return ToolResult(ok=False, error=f"http error: {exc}")
        text = resp.text[:8192]
        return ToolResult(
            ok=resp.is_success,
            output=text,
            error=None if resp.is_success else f"HTTP {resp.status_code}",
            data={
                "status_code": resp.status_code,
                "content_type": resp.headers.get("content-type", ""),
            },
        )
