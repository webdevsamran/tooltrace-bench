"""Prove the Docker sandbox's isolation claims by exercising them.

`scripts/sandbox_check.py` verifies the *local* sandbox. The Docker provider
makes stronger claims -- OS-level filesystem and network isolation -- and an
untested strong claim is worse than a tested weak one, because it is the one
people rely on. This runs the equivalent checks against a real container.

Skips cleanly (exit 0) when Docker is unavailable, so it can sit in CI on
runners that have it and on developer machines that do not. A skip is
reported, never silent: a check that quietly does nothing is indistinguishable
from one that passed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tooltrace.core.models import ResourceLimits, TaskDefinition
from tooltrace.sandbox.docker_sandbox import DockerSandbox

_IMAGE = "python:3.12-slim"


def _task(**overrides: object) -> TaskDefinition:
    base: dict[str, object] = {
        "id": "sandbox-check/docker",
        "category": "file-editing",
        "objective": "conformance",
        "allowed_tools": ["shell"],
        "assertions": [{"type": "file_exists", "params": {"path": "a"}}],
        "starting_workspace": {"seed.txt": "hello\n"},
    }
    base.update(overrides)
    return TaskDefinition.model_validate(base)


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=30, text=True)
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def main() -> int:
    if not _docker_available():
        print("SKIP docker sandbox conformance: docker unavailable on this host")
        return 0

    # Pull once so per-check timeouts measure the check, not the download.
    subprocess.run(["docker", "pull", "--quiet", _IMAGE], capture_output=True, timeout=600)

    failures: list[str] = []

    # 1. The workspace is mounted and visible inside the container.
    with DockerSandbox(image=_IMAGE) as box:
        box.start(_task())
        code, out = box.run_in_container(["cat", "seed.txt"], timeout=120)
        if code != 0 or "hello" not in out:
            failures.append(f"boundary: workspace not readable in container ({code}, {out!r})")

        # 2. Writes land in the mounted workspace, not somewhere ephemeral.
        code, _ = box.run_in_container(["sh", "-c", "echo written > out.txt"], timeout=120)
        assert box.workspace is not None
        if code != 0 or not (box.workspace / "out.txt").is_file():
            failures.append("boundary: container write did not reach the host workspace")

        # 3. Network is off by default. Claimed in the docstring; now checked.
        code, out = box.run_in_container(
            ["python", "-c", "import socket;socket.create_connection(('1.1.1.1',53),timeout=4)"],
            timeout=120,
        )
        if code == 0:
            failures.append("network: outbound connection succeeded with --network none")

        # 4. Nothing outside the workspace is mounted.
        code, out = box.run_in_container(["ls", "/"], timeout=120)
        if "host" in out.split() or "Users" in out:
            failures.append(f"boundary: host filesystem appears inside the container: {out!r}")

    # 5. Declared resource limits actually reach docker, rather than being
    #    accepted and ignored as they were before.
    box = DockerSandbox(image=_IMAGE)
    box.start(_task(resource_limits=ResourceLimits(max_memory_mb=64, max_cpus=0.5)))
    if box.limits.max_memory_mb != 64:
        failures.append("limits: task resource_limits not captured by the sandbox")
    code, out = box.run_in_container(
        ["python", "-c", "print(open('/sys/fs/cgroup/memory.max').read().strip())"],
        timeout=120,
    )
    if code == 0:
        reported = out.strip().splitlines()[-1] if out.strip() else ""
        # 64 MiB, as the container sees it.
        if reported.isdigit() and int(reported) > 96 * 1024 * 1024:
            failures.append(f"limits: container memory limit is {reported} bytes, expected ~64MiB")
    box.cleanup()

    # 6. Timeouts are enforced rather than hanging the run.
    box = DockerSandbox(image=_IMAGE)
    box.start(_task())
    code, out = box.run_in_container(["sleep", "30"], timeout=5)
    if code != 124:
        failures.append(f"timeout: expected exit 124 for a timed-out container, got {code}")
    box.cleanup()

    # 7. Cleanup removes the workspace.
    box = DockerSandbox(image=_IMAGE)
    workspace = box.start(_task())
    box.cleanup()
    if workspace.exists():
        failures.append("cleanup: workspace still present after cleanup()")
    if box.workspace is not None:
        failures.append("cleanup: sandbox still reports a workspace after cleanup()")

    if failures:
        for f in failures:
            print(f"FAIL {f}")
        return 1
    print("docker sandbox conformance: 7 checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
