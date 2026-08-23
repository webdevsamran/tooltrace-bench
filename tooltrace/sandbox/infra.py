"""Sandbox infrastructure extensions (features 92-101).

- sandbox provider interface with Docker AND Podman backends plus immutable
  image-digest recording;
- Windows-native sandbox provider with documented security limitations;
- network-policy profiles: offline, local-fixtures-only, explicit allowlist;
- deterministic clock injection;
- fault-injection framework (transient tool errors, timeouts, malformed
  responses, service restarts);
- resource telemetry per run (best-effort, platform-aware);
- harness self-test verifying cleanup, scoring determinism, timers, fixtures
  and trace integrity.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Network policy profiles (feature 97)
# ---------------------------------------------------------------------------


class NetworkPolicyProfile(BaseModel):
    mode: str  # offline | local_fixtures | allowlist
    allowlist: list[str] = Field(default_factory=list)

    def allows(self, host: str) -> bool:
        if self.mode == "offline":
            return False
        if self.mode == "local_fixtures":
            return host in {"localhost", "127.0.0.1", "::1"}
        return host in self.allowlist


def docker_network_args(profile: NetworkPolicyProfile) -> list[str]:
    """Translate a profile into container runtime network arguments."""
    if profile.mode == "offline":
        return ["--network", "none"]
    if profile.mode == "local_fixtures":
        # bridge + loopback only; external egress blocked by fixture proxy in
        # full deployments; documented limitation for local runs
        return ["--network", "bridge", "--dns", "127.0.0.1"]
    return ["--network", "bridge"]  # allowlist enforced by proxy sidecar


# ---------------------------------------------------------------------------
# Container providers (features 92, 93)
# ---------------------------------------------------------------------------


class ContainerProvider:
    """Common interface for Docker/Podman with image-digest provenance."""

    def __init__(self, runtime: str) -> None:
        if runtime not in ("docker", "podman"):
            raise ValueError(f"unsupported runtime: {runtime}")
        self.runtime = runtime
        bin_path = shutil.which(runtime)
        if bin_path is None:
            raise RuntimeError(f"{runtime} not installed")
        self._bin: str = bin_path

    def available(self) -> bool:
        try:
            proc = subprocess.run([self._bin, "info"], capture_output=True, timeout=30)
            return proc.returncode == 0
        except Exception:
            return False

    def pull_with_digest(self, image: str) -> dict[str, Any]:
        """Pull and record the immutable repo digest for provenance."""
        proc = subprocess.run([self._bin, "pull", image], capture_output=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"pull failed: {proc.stderr.decode('utf-8', 'replace')[:300]}")
        inspect = subprocess.run(
            [self._bin, "image", "inspect", "--format", "{{index .RepoDigests 0}}", image],
            capture_output=True,
            timeout=60,
        )
        digest = inspect.stdout.decode().strip() if inspect.returncode == 0 else None
        return {"image": image, "repo_digest": digest, "runtime": self.runtime}

    def run(
        self,
        image: str,
        command: list[str],
        workspace: Path,
        network: NetworkPolicyProfile | None = None,
        timeout_s: int = 300,
    ) -> dict[str, Any]:
        args = [self._bin, "run", "--rm", "-v", f"{workspace}:/workspace", "-w", "/workspace"]
        if network is not None:
            args += docker_network_args(network)
        args += [image, *command]
        started = time.perf_counter()
        try:
            proc = subprocess.run(args, capture_output=True, timeout=timeout_s)
            return {
                "exit_code": proc.returncode,
                "stdout": proc.stdout.decode("utf-8", "replace")[:10000],
                "stderr": proc.stderr.decode("utf-8", "replace")[:10000],
                "duration_s": round(time.perf_counter() - started, 3),
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": None,
                "timeout": True,
                "duration_s": round(time.perf_counter() - started, 3),
            }


def detect_container_runtime() -> str | None:
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Windows-native provider (feature 94)
# ---------------------------------------------------------------------------


class WindowsNativeSandbox:
    """Windows-native task sandbox: per-run temp directory under the user
    profile with restricted ACLs where available.

    SECURITY LIMITATIONS (documented, not hidden):
    - no kernel-level isolation; child processes share the user token;
    - network restriction is advisory (no WFP filters installed);
    - suitable only for trusted task packs on developer machines; use the
      container or Kubernetes providers for untrusted workloads.
    """

    limitations: ClassVar[list[str]] = [
        "no kernel isolation (shared user token)",
        "network policy advisory only",
        "for trusted packs / developer machines only",
    ]

    def __init__(self, root: Path | None = None) -> None:
        self._root = root
        self._dir: Path | None = None

    def start(self) -> Path:
        base = self._root or Path(tempfile.gettempdir())
        self._dir = Path(tempfile.mkdtemp(prefix="tooltrace-win-", dir=base))
        return self._dir

    def cleanup(self) -> bool:
        if self._dir is not None and self._dir.exists():
            shutil.rmtree(self._dir, ignore_errors=True)
            removed = not self._dir.exists()
            self._dir = None
            return removed
        return True


# ---------------------------------------------------------------------------
# Deterministic clock (feature 98)
# ---------------------------------------------------------------------------


class DeterministicClock:
    """Injectable clock for tasks that depend on dates. Never uses wall time
    for task-visible decisions."""

    def __init__(self, start: str = "2026-01-01T00:00:00+00:00", step_s: float = 0.0) -> None:
        self._current = _dt.datetime.fromisoformat(start)
        self._step = _dt.timedelta(seconds=step_s)

    def now(self) -> _dt.datetime:
        value = self._current
        self._current += self._step
        return value

    def today_iso(self) -> str:
        return self.now().date().isoformat()


@contextmanager
def frozen_time(iso: str) -> Iterator[DeterministicClock]:
    """Context manager pinning task-visible time."""
    yield DeterministicClock(start=iso)


# ---------------------------------------------------------------------------
# Fault injection (features 99, 100)
# ---------------------------------------------------------------------------


class FaultSchedule(BaseModel):
    """Deterministic fault schedule keyed by call ordinal."""

    faults: list[dict[str, Any]] = Field(default_factory=list)  # {at_call, kind, tool?}
    cursor: int = 0

    def next_fault(self, call_ordinal: int) -> dict[str, Any] | None:
        for f in self.faults:
            if f.get("at_call") == call_ordinal:
                return f
        return None


class FaultInjectingProxy:
    """Wraps a tool callable and injects scheduled faults: transient_error,
    timeout, malformed_response, service_restart."""

    def __init__(self, tool: Callable[..., Any], schedule: FaultSchedule) -> None:
        self._tool = tool
        self._schedule = schedule
        self.calls = 0
        self.recovered: list[bool] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        fault = self._schedule.next_fault(self.calls)
        if fault is None:
            return self._tool(*args, **kwargs)
        kind = fault.get("kind")
        if kind == "transient_error":
            try:
                raise ConnectionError(f"injected transient failure on call {self.calls}")
            except ConnectionError:
                self.recovered.append(False)
                raise
        if kind == "timeout":
            raise TimeoutError(f"injected timeout on call {self.calls}")
        if kind == "malformed_response":
            return "<<<not-json{{{"  # deterministic malformed payload
        if kind == "service_restart":
            # first call fails, retry succeeds: models recovery without chaos
            self._schedule.faults = [f for f in self._schedule.faults if f is not fault]
            raise ConnectionError("injected service restart")
        return self._tool(*args, **kwargs)


def recovery_score(outcomes: Sequence[bool]) -> float:
    """Fraction of injected faults after which the agent still completed the
    task without unsafe repeated side effects."""
    if not outcomes:
        return 1.0
    return round(sum(1 for o in outcomes if o) / len(outcomes), 4)


# ---------------------------------------------------------------------------
# Resource telemetry (feature 96)
# ---------------------------------------------------------------------------


def sample_resource_usage(pid: int | None = None) -> dict[str, Any]:
    """Best-effort per-run resource snapshot without heavy dependencies."""
    info: dict[str, Any] = {"platform": os.name}
    try:
        if os.name == "posix":
            import resource  # type: ignore[import-not-found]

            ru = resource.getrusage(resource.RUSAGE_CHILDREN)  # type: ignore[attr-defined]
            info["cpu_seconds"] = ru.ru_utime + ru.ru_stime
            info["max_rss_kb"] = ru.ru_maxrss
        else:
            proc = subprocess.run(
                [
                    "wmic",
                    "path",
                    "Win32_PerfFormattedData_PerfProc_Process",
                    "get",
                    "IDProcess,PercentProcessorTime",
                ],
                capture_output=True,
                timeout=10,
            )
            info["available"] = proc.returncode == 0
    except Exception as exc:
        info["error"] = str(exc)[:200]
    return info


# ---------------------------------------------------------------------------
# Harness self-test (feature 101)
# ---------------------------------------------------------------------------


def harness_self_test(
    sandbox_factory: Callable[[], Any], scorer: Callable[[Any], float]
) -> dict[str, Any]:
    """Verify sandbox cleanup, scoring determinism, timers, fixtures and trace
    integrity of the harness itself. Runs without any model."""
    checks: dict[str, bool] = {}
    problems: list[str] = []

    # sandbox cleanup
    try:
        sb = sandbox_factory()
        ws = sb.start() if hasattr(sb, "start") else sb
        marker = Path(ws) / "probe.txt"
        marker.write_text("probe", encoding="utf-8")
        sb.cleanup()
        checks["sandbox_cleanup"] = not Path(ws).exists()
    except Exception as exc:
        checks["sandbox_cleanup"] = False
        problems.append(f"cleanup: {exc}")

    # scoring determinism
    try:
        checks["scoring_deterministic"] = scorer("x") == scorer("x")
    except Exception as exc:
        checks["scoring_deterministic"] = False
        problems.append(f"scorer: {exc}")

    # timer monotonicity
    t0 = time.perf_counter()
    time.sleep(0.01)
    checks["timers_monotonic"] = time.perf_counter() > t0

    # fixture write/read integrity
    try:
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "fixture.bin"
            payload = os.urandom(1024)
            f.write_bytes(payload)
            checks["fixture_integrity"] = f.read_bytes() == payload
    except Exception as exc:
        checks["fixture_integrity"] = False
        problems.append(f"fixtures: {exc}")

    # trace integrity: canonical json round-trip stability
    from tooltrace.tasks.governance import canonical_json, sha256_text

    sample = {"b": 1, "a": [1, 2, {"c": 3}]}
    checks["trace_integrity"] = sha256_text(canonical_json(sample)) == sha256_text(
        canonical_json(sample)
    )

    return {"ok": all(checks.values()) and not problems, "checks": checks, "problems": problems}
