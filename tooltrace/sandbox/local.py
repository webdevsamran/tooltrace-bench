"""Default sandbox: temporary-workspace isolation.

Guarantees (see docs/threat-model.md for honest limits):

- every task runs in a fresh temporary directory that is removed afterwards;
- all tool file access is enforced against the workspace boundary;
- network access is denied at the tool layer unless explicitly allowlisted;
- subprocesses receive only an allowlisted environment;
- timeouts bound every subprocess.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from tooltrace.core.exceptions import SandboxError
from tooltrace.core.models import TaskDefinition


class TempWorkspaceSandbox:
    """Fresh temporary workspace per task run."""

    name = "local"

    def __init__(self) -> None:
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self.workspace: Path | None = None

    def start(self, task: TaskDefinition) -> Path:
        self._tmp = tempfile.TemporaryDirectory(prefix="tooltrace-")
        root = Path(self._tmp.name)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        try:
            for rel, content in task.starting_workspace.items():
                target = self.workspace / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            fixtures_dir = root / "fixtures"
            fixtures_dir.mkdir()
            for rel, content in task.fixtures.items():
                target = fixtures_dir / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        except OSError as exc:
            self.cleanup()
            raise SandboxError(f"failed to materialize workspace: {exc}") from exc
        return self.workspace

    @property
    def fixtures_dir(self) -> Path | None:
        if self._tmp is None:
            return None
        return Path(self._tmp.name) / "fixtures"

    def cleanup(self) -> None:
        if self._tmp is not None:
            try:
                self._tmp.cleanup()
            except OSError:
                shutil.rmtree(self._tmp.name, ignore_errors=True)  # type: ignore[arg-type]
            finally:
                self._tmp = None
                self.workspace = None

    def __enter__(self) -> TempWorkspaceSandbox:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()
