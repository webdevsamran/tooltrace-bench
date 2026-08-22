"""Typed tool implementations. Importing this package registers all
built-in tools in ``tool_registry``."""

from tooltrace.tools.base import (
    Tool,
    ToolContext,
    ToolResult,
    resolve_in_workspace,
    summarize_args,
)
from tooltrace.tools.compute import CalculatorTool
from tooltrace.tools.executor import ExecutionStats, ToolExecutor
from tooltrace.tools.files import (
    ListDirectoryTool,
    PatchFileTool,
    ReadFileTool,
    SearchTextTool,
    WriteFileTool,
)
from tooltrace.tools.net import HttpTool
from tooltrace.tools.process import GitTool, ShellTool, TestRunnerTool

__all__ = [
    "CalculatorTool",
    "ExecutionStats",
    "GitTool",
    "HttpTool",
    "ListDirectoryTool",
    "PatchFileTool",
    "ReadFileTool",
    "SearchTextTool",
    "ShellTool",
    "TestRunnerTool",
    "Tool",
    "ToolContext",
    "ToolExecutor",
    "ToolResult",
    "WriteFileTool",
    "resolve_in_workspace",
    "summarize_args",
]
