"""File-operation tools: read_file, write_file, patch_file, list_directory,
search_text. All paths are enforced inside the sandbox workspace."""

from __future__ import annotations

import re
from typing import ClassVar

from tooltrace.core.registry import tool_registry
from tooltrace.tools.base import Tool, ToolContext, ToolResult, resolve_in_workspace

MAX_READ_BYTES = 256 * 1024
NL = chr(10)


@tool_registry.register("read_file")
class ReadFileTool(Tool):
    name: str = "read_file"
    description = "Read a text file inside the workspace."

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        path = resolve_in_workspace(ctx.workspace, args.get("path"))
        if not path.is_file():
            return ToolResult(ok=False, error=f"file not found: {args.get('path')}")
        raw = path.read_bytes()
        truncated = len(raw) > MAX_READ_BYTES
        text = raw[:MAX_READ_BYTES].decode("utf-8", errors="replace")
        note = " (truncated)" if truncated else ""
        return ToolResult(
            ok=True,
            output=text + note,
            data={"path": str(path.relative_to(ctx.workspace.resolve())), "bytes": len(raw)},
        )


@tool_registry.register("write_file")
class WriteFileTool(Tool):
    name: str = "write_file"
    description = "Create or overwrite a text file inside the workspace."

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        path = resolve_in_workspace(ctx.workspace, args.get("path"))
        content = args.get("content", "")
        if not isinstance(content, str):
            return ToolResult(ok=False, error="content must be a string")
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        action = "overwrote" if existed else "created"
        return ToolResult(
            ok=True,
            output=f"{action} {path.name} ({len(content)} chars)",
            data={"path": str(path.relative_to(ctx.workspace.resolve())), "action": action},
        )


@tool_registry.register("patch_file")
class PatchFileTool(Tool):
    name: str = "patch_file"
    description = (
        "Replace an exact substring in a workspace file. Fails cleanly when "
        "the search text is absent or ambiguous."
    )

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        path = resolve_in_workspace(ctx.workspace, args.get("path"))
        search = args.get("search")
        replace = args.get("replace", "")
        if not isinstance(search, str) or not isinstance(replace, str):
            return ToolResult(ok=False, error="search and replace must be strings")
        if not path.is_file():
            return ToolResult(ok=False, error=f"file not found: {args.get('path')}")
        text = path.read_text(encoding="utf-8")
        count = text.count(search)
        if count == 0:
            return ToolResult(ok=False, error="search text not found in file")
        if count > 1 and not args.get("replace_all"):
            return ToolResult(
                ok=False,
                error=f"search text matches {count} locations; pass replace_all=true or widen context",
                data={"matches": count},
            )
        new_text = (
            text.replace(search, replace)
            if args.get("replace_all")
            else text.replace(search, replace, 1)
        )
        path.write_text(new_text, encoding="utf-8")
        return ToolResult(
            ok=True,
            output=f"patched {path.name} ({count} replacement(s))",
            data={"path": str(path.relative_to(ctx.workspace.resolve())), "replacements": count},
        )


@tool_registry.register("list_directory")
class ListDirectoryTool(Tool):
    name: str = "list_directory"
    description = "List files and directories under a workspace path."

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        rel = args.get("path", ".")
        path = resolve_in_workspace(ctx.workspace, rel)
        if not path.is_dir():
            return ToolResult(ok=False, error=f"not a directory: {rel}")
        entries: list[dict[str, object]] = []
        for child in sorted(path.iterdir()):
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        listing = NL.join(f"{e['type']:<5} {e['name']}" for e in entries) or "(empty)"
        return ToolResult(ok=True, output=listing, data={"entries": entries})


@tool_registry.register("search_text")
class SearchTextTool(Tool):
    name: str = "search_text"
    description = "Search file contents under a workspace path (literal or regex)."

    MAX_MATCHES: ClassVar[int] = 200

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            return ToolResult(ok=False, error="pattern must be a non-empty string")
        use_regex = bool(args.get("regex", False))
        try:
            matcher = re.compile(pattern) if use_regex else None
        except re.error as exc:
            return ToolResult(ok=False, error=f"invalid regex: {exc}")
        root_arg = args.get("path", ".")
        root = resolve_in_workspace(ctx.workspace, root_arg)
        if not root.is_dir():
            return ToolResult(ok=False, error=f"not a directory: {root_arg}")

        matches: list[dict[str, object]] = []
        for f in sorted(root.rglob("*")):
            if not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                hit = matcher.search(line) if matcher else (pattern in line)
                if hit:
                    rel = str(f.relative_to(root))
                    matches.append({"file": rel, "line": lineno, "text": line.strip()[:200]})
                    if len(matches) >= self.MAX_MATCHES:
                        break
            if len(matches) >= self.MAX_MATCHES:
                break
        truncated = len(matches) >= self.MAX_MATCHES
        summary = f"{len(matches)} match(es)" + (" (truncated)" if truncated else "")
        lines = [f"{m['file']}:{m['line']}: {m['text']}" for m in matches]
        return ToolResult(
            ok=True,
            output=NL.join(lines) or "no matches",
            data={"matches": matches},
            error=None if matches else summary,
        )
