"""Controlled, benign fault injection for reliability testing.

Perturbations are deterministic (each spec fires once at its first matching
opportunity unless ``params.every`` is true) and never contain offensive
payloads — they simulate ordinary operational failures so we can measure
whether an agent recovers.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from tooltrace.core.models import PerturbationSpec


class PerturbationEngine:
    def __init__(self, specs: list[PerturbationSpec]) -> None:
        self._specs = list(specs)
        self._fired: set[int] = set()
        self.injected_count = 0

    # -- pre-run workspace mutations ----------------------------------------

    def prepare_workspace(self, workspace: Path) -> None:
        """Apply perturbations that modify the starting workspace."""
        for i, spec in enumerate(self._specs):
            if spec.kind == "moved_file" and i not in self._fired:
                src = str(spec.params.get("from", ""))
                dst = str(spec.params.get("to", ""))
                source = workspace / src
                target = workspace / dst
                if source.is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
                    self._fired.add(i)
                    self.injected_count += 1
            elif spec.kind == "irrelevant_files" and i not in self._fired:
                for rel, content in dict(spec.params.get("files", {})).items():  # type: ignore[arg-type]
                    target = workspace / str(rel)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(str(content), encoding="utf-8")
                self._fired.add(i)
                self.injected_count += 1

    # -- runtime hook ---------------------------------------------------------

    def hook(self, tool_name: str, args: dict[str, object]) -> str | None:
        """Return an injected error message for this call, or None."""
        for i, spec in enumerate(self._specs):
            if i in self._fired and not spec.params.get("every"):
                continue
            match = self._matches(spec, tool_name, args)
            if not match:
                continue
            self._fired.add(i)
            self.injected_count += 1
            return self._message_for(spec)
        return None

    def _matches(self, spec: PerturbationSpec, tool_name: str, args: dict[str, object]) -> bool:
        target_tool = spec.params.get("tool")
        if target_tool and target_tool != tool_name:
            return False
        if spec.kind == "delay":
            return True  # delays apply to any matching call
        if spec.kind == "api_error":
            return tool_name == "http"
        if spec.kind in {"tool_failure", "command_exit", "ambiguous_error"}:
            return bool(target_tool)
        return False

    def _message_for(self, spec: PerturbationSpec) -> str | None:
        kind = spec.kind
        if kind == "delay":
            seconds = float(spec.params.get("seconds", 0.5))  # type: ignore[arg-type]
            time.sleep(min(seconds, 5.0))
            return None  # a delay slows the call but does not fail it
        if kind == "command_exit":
            code = int(spec.params.get("exit_code", 1))  # type: ignore[arg-type]
            return f"injected failure: command exited with code {code}"
        if kind == "api_error":
            status = int(spec.params.get("status", 503))  # type: ignore[arg-type]
            return f"injected failure: mock API returned HTTP {status}"
        if kind == "ambiguous_error":
            return "operation failed (unclear cause; see logs)"
        return f"injected transient failure of tool {spec.params.get('tool', '?')}"

    @property
    def active(self) -> bool:
        return bool(self._specs)


def environment_note() -> str:
    """Documents that network-level faults are simulated at the tool layer."""
    return (
        "Note: api_error perturbations are injected at the HTTP-tool layer; "
        f"no real network traffic is generated (pid={os.getpid()})."
    )
