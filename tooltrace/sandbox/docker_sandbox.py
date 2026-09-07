"""Optional Docker sandbox provider (extra: ``tooltrace[docker]``).

Runs the task workspace inside a container with ``--network none`` by
default, giving OS-level filesystem and network isolation that the local
sandbox cannot claim. Requires the ``docker`` CLI; degrades loudly, never
silently.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from tooltrace.core.exceptions import SandboxError
from tooltrace.core.models import ResourceLimits, TaskDefinition


class DockerSandbox:
    """Container-isolated workspace. Image must contain python3."""

    name = "docker"

    #: Applied when a task declares no limit of its own. Chosen to be small
    #: enough that a runaway task cannot take the host down, and large enough
    #: that ordinary work is unaffected.
    DEFAULT_MEMORY_MB = 512
    DEFAULT_CPUS = 1.0

    def __init__(self, image: str = "python:3.12-slim", network: str = "none") -> None:
        self.image = image
        self.network = network
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.workspace: Path | None = None
        #: Populated by start() from the task, so run_in_container applies the
        #: task's declared limits rather than a hardcoded pair.
        self.limits: ResourceLimits = ResourceLimits()

    def _require_docker(self) -> None:
        if shutil.which("docker") is None:
            raise SandboxError(
                "Docker sandbox requested but the 'docker' CLI was not found. "
                "Install Docker or use the default local sandbox."
            )

    def start(self, task: TaskDefinition) -> Path:
        self._require_docker()
        self.limits = task.resource_limits
        self._tmp = tempfile.TemporaryDirectory(prefix="tooltrace-docker-")
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        for rel, content in task.starting_workspace.items():
            target = self.workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return self.workspace

    def run_in_container(self, command: list[str], timeout: float = 60.0) -> tuple[int, str]:
        """Execute *command* inside the container against the mounted workspace."""
        if self.workspace is None:
            raise SandboxError("sandbox not started")
        # Limits come from the task, falling back to the class defaults. They
        # were previously hardcoded, so a task declaring resource_limits got
        # 512m/1.0 regardless of what it asked for -- the declaration was
        # accepted and silently ignored.
        memory_mb = self.limits.max_memory_mb or self.DEFAULT_MEMORY_MB
        cpus = self.limits.max_cpus or self.DEFAULT_CPUS
        cmd = [
            "docker",
            "run",
            "--rm",
            "--network",
            self.network,
            "--memory",
            f"{int(memory_mb)}m",
            # Without this a container that exhausts its memory limit is
            # allowed to swap instead of being OOM-killed, so the limit does
            # not bound anything in wall-clock terms.
            "--memory-swap",
            f"{int(memory_mb)}m",
            "--cpus",
            str(float(cpus)),
            "--pids-limit",
            "256",
            "-v",
            f"{self.workspace}:/workspace",
            "-w",
            "/workspace",
            self.image,
            *command,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
        except subprocess.TimeoutExpired:
            return 124, "[container timeout]"
        except OSError as exc:
            raise SandboxError(f"failed to invoke docker: {exc}") from exc
        output = proc.stdout + proc.stderr
        return proc.returncode, output[: 64 * 1024]

    def cleanup(self) -> None:
        if self._tmp is not None:
            shutil.rmtree(self._tmp.name, ignore_errors=True)
            self._tmp = None
            self.workspace = None

    def __enter__(self) -> DockerSandbox:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()
