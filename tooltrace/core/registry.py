"""Plugin registries and entry-point discovery.

Core components (tools, agents, scorers, sandboxes, reporters, task packs) are
registered in-process via decorators and discovered from installed packages via
importlib metadata entry-point groups:

    tooltrace.agents / tooltrace.tools / tooltrace.task_packs /
    tooltrace.scorers / tooltrace.reporters / tooltrace.sandboxes
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable
from typing import Any, Generic, TypeVar

T = TypeVar("T")

ENTRY_POINT_GROUPS: dict[str, str] = {
    "agents": "tooltrace.agents",
    "tools": "tooltrace.tools",
    "task_packs": "tooltrace.task_packs",
    "scorers": "tooltrace.scorers",
    "reporters": "tooltrace.reporters",
    "sandboxes": "tooltrace.sandboxes",
}


class Registry(Generic[T]):
    """A name -> factory registry with optional entry-point discovery."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._items: dict[str, T] = {}
        self._discovered = False

    def register(self, name: str) -> Callable[[T], T]:
        def decorator(item: T) -> T:
            self._items[name] = item
            return item

        return decorator

    def _load_entry_points(self) -> None:
        if self._discovered:
            return
        self._discovered = True
        group = ENTRY_POINT_GROUPS.get(self.kind)
        if group is None:
            return
        try:
            eps = importlib.metadata.entry_points(group=group)
        except TypeError:  # pragma: no cover - very old Python fallback
            eps = importlib.metadata.entry_points().get(group, [])  # type: ignore[attr-defined]
        for ep in eps:
            try:
                loaded = ep.load()
            except Exception:
                continue
            self._items.setdefault(ep.name, loaded)

    def get(self, name: str) -> T:
        self._load_entry_points()
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(
                f"Unknown {self.kind} {name!r}. Available: {sorted(self._items)}"
            ) from None

    def has(self, name: str) -> bool:
        self._load_entry_points()
        return name in self._items

    def names(self) -> list[str]:
        self._load_entry_points()
        return sorted(self._items)

    def items(self) -> list[tuple[str, T]]:
        self._load_entry_points()
        return sorted(self._items.items())


def discover_plugins(group: str) -> dict[str, Any]:
    """Load every plugin registered under an arbitrary entry-point group."""
    out: dict[str, Any] = {}
    try:
        eps = importlib.metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover
        eps = importlib.metadata.entry_points().get(group, [])  # type: ignore[attr-defined]
    for ep in eps:
        try:
            out[ep.name] = ep.load()
        except Exception:
            continue
    return out


# Shared registries -----------------------------------------------------------

tool_registry: Registry[Any] = Registry("tools")
agent_registry: Registry[Any] = Registry("agents")
scorer_registry: Registry[Any] = Registry("scorers")
sandbox_registry: Registry[Any] = Registry("sandboxes")
reporter_registry: Registry[Any] = Registry("reporters")


def load_all_registries() -> None:
    """Import core modules so built-ins are registered before use."""
    from tooltrace import agents as _agents  # noqa: F401
    from tooltrace import sandbox as _sandbox  # noqa: F401
    from tooltrace import scoring as _scoring  # noqa: F401
    from tooltrace import tools as _tools  # noqa: F401
