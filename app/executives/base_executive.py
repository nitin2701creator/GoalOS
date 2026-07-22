"""Common contract implemented by all GoalOS executives."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.executives.executive_models import (
    ExecutiveAlert,
    ExecutiveKPI,
    ExecutivePriority,
    ExecutiveRecommendation,
    ExecutiveSummary,
)


class BaseExecutive(ABC):
    """Implementation-independent lifecycle and reporting contract for executives."""

    name: str
    description: str

    def __init__(self, name: str, description: str) -> None:
        """Initialize the executive's stable runtime identity.

        Args:
            name: Unique human-readable executive name.
            description: Human-readable executive responsibility.
        """

        self.name = self._require_text(name, "name")
        self.description = self._require_text(description, "description")

    @abstractmethod
    def initialize(self) -> None:
        """Prepare the executive for use by the runtime."""

    @abstractmethod
    def shutdown(self) -> None:
        """Release resources held by the executive."""

    @abstractmethod
    def health_check(self) -> bool:
        """Return whether the executive is currently ready to operate."""

    @abstractmethod
    def get_summary(self) -> ExecutiveSummary:
        """Return the executive's current normalized summary."""

    @abstractmethod
    def get_kpis(self) -> tuple[ExecutiveKPI, ...]:
        """Return the executive's current key performance indicators."""

    @abstractmethod
    def get_alerts(self) -> tuple[ExecutiveAlert, ...]:
        """Return active alerts owned by this executive."""

    @abstractmethod
    def get_priorities(self) -> tuple[ExecutivePriority, ...]:
        """Return the executive's ranked priorities."""

    @abstractmethod
    def get_recommendations(self) -> tuple[ExecutiveRecommendation, ...]:
        """Return the executive's current recommendations."""

    @abstractmethod
    def execute(self, action: str, **kwargs: Any) -> Any:
        """Execute a named action without exposing implementation details."""

    @abstractmethod
    def supported_integrations(self) -> tuple[str, ...]:
        """Return stable names of integrations this executive can use."""

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        """Normalize required text and reject blank values."""

        if not isinstance(value, str) or not (normalized_value := value.strip()):
            raise ValueError(f"{field_name} is required")
        return normalized_value
