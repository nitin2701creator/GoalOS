"""Base primitives for GoalOS skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """Abstract lifecycle contract for a GoalOS skill.

    Skills provide domain-specific behaviour. The runtime only manages their
    lifecycle and delegates execution to concrete implementations.
    """

    name: str
    description: str

    def __init__(self, name: str, description: str) -> None:
        """Initialize immutable skill identity metadata.

        Args:
            name: Stable, unique name used by the runtime registry.
            description: Human-readable summary of the skill.

        Raises:
            ValueError: If either value is blank.
        """

        self.name = self._require_text(name, "name")
        self.description = self._require_text(description, "description")

    @abstractmethod
    def initialize(self) -> None:
        """Prepare the skill for execution."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release resources held by the skill."""

    @abstractmethod
    async def execute(self, context: Any) -> Any:
        """Execute the skill for the supplied runtime context."""

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        """Normalize and validate required skill metadata."""

        if not isinstance(value, str) or not (normalized_value := value.strip()):
            raise ValueError(f"{field_name} is required")
        return normalized_value
