"""Memory boundary for the Autonomous Development System."""

from __future__ import annotations

from typing import Any


class DevelopmentMemory:
    """In-memory ADS session and learning context."""

    def __init__(self) -> None:
        self._entries: dict[str, Any] = {}

    def recall(self, key: str) -> Any | None:
        """Recall a stored value, if present."""

        return self._entries.get(key)

    def remember(self, key: str, value: Any) -> None:
        """Store ``value`` under a task-scoped key."""

        self._entries[key] = value
