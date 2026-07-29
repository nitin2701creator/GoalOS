"""Reusable health models for GoalOS integrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConnectorHealthStatus(str, Enum):
    """Supported states reported by a connector."""

    HEALTHY = "Healthy"
    DISCONNECTED = "Disconnected"
    AUTHENTICATION_REQUIRED = "Authentication Required"
    ERROR = "Error"


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    """An immutable connector health report.

    Attributes:
        status: Current operational state.
        message: Optional human-readable health detail.
    """

    status: ConnectorHealthStatus
    message: str | None = None

    @property
    def is_healthy(self) -> bool:
        """Return whether the connector is ready to serve requests."""

        return self.status is ConnectorHealthStatus.HEALTHY
