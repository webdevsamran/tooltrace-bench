"""Targeted tests raising coverage of CLI, SDK, repro, security, scoring,
perturbations, failure classification and remaining adapters."""

from __future__ import annotations

import pytest
from tooltrace.core.models import TraceEvent

from tests.conftest import make_task


def _ev(type_: str, payload: dict) -> TraceEvent:
    return TraceEvent(timestamp="t", seq=1, type=type_, payload=payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


class TestDockerSandboxGuard:
    def test_import_and_guard(self) -> None:
        pytest.importorskip("tooltrace.sandbox.docker_sandbox")
        from tooltrace.sandbox.docker_sandbox import DockerSandbox

        sb = DockerSandbox()
        try:
            ws = sb.start(make_task())
        except Exception as exc:
            # acceptable when docker daemon/image unavailable in the environment
            assert "docker" in str(exc).lower() or "image" in str(exc).lower()
        else:
            assert ws.exists()
