"""Sandbox providers and workspace diffing."""

from tooltrace.sandbox.diff import changed_paths, snapshot, workspace_diff
from tooltrace.sandbox.docker_sandbox import DockerSandbox
from tooltrace.sandbox.local import TempWorkspaceSandbox

__all__ = [
    "DockerSandbox",
    "TempWorkspaceSandbox",
    "changed_paths",
    "snapshot",
    "workspace_diff",
]
