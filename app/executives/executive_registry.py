"""Instance registry for GoalOS executives."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from app.executives.base_executive import BaseExecutive


class ExecutiveRegistry:
    """Own executive instances for a single executive runtime."""

    def __init__(self) -> None:
        """Create an empty registry without process-wide mutable state."""

        self._executives: dict[str, BaseExecutive] = {}

    def register(self, executive: BaseExecutive) -> None:
        """Register an executive under its unique name.

        Raises:
            TypeError: If the value is not a ``BaseExecutive`` instance.
            ValueError: If the executive name is already registered.
        """

        if not isinstance(executive, BaseExecutive):
            raise TypeError("executive must inherit BaseExecutive")
        name = self._normalize_name(executive.name)
        if name in self._executives:
            raise ValueError(f"Executive already registered: {name}")
        self._executives[name] = executive

    def unregister(self, name: str) -> BaseExecutive | None:
        """Remove and return an executive by name, if it is registered."""

        return self._executives.pop(self._normalize_name(name), None)

    def get(self, name: str) -> BaseExecutive | None:
        """Return an executive by name, if it is registered."""

        return self._executives.get(self._normalize_name(name))

    def list(self) -> tuple[str, ...]:
        """Return registered executive names in deterministic order."""

        return tuple(sorted(self._executives))

    def exists(self, name: str) -> bool:
        """Return whether an executive is registered under ``name``."""

        return self._normalize_name(name) in self._executives

    def snapshot(self) -> Mapping[str, BaseExecutive]:
        """Return an immutable snapshot of registered executives."""

        return MappingProxyType(dict(self._executives))

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize an executive registry key."""

        if not isinstance(name, str) or not (normalized_name := name.strip()):
            raise ValueError("executive name is required")
        return normalized_name.casefold()
