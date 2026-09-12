"""Reusable health models for GoalOS integrations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConnectorHealthStatus(str, Enum):
    """Supported states reported by a connector."""

    HEALTHY = "Healthy"
    DISCONNECTED = "Disconnected"
    NOT_CONFIGURED = "Not Configured"
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


class ConnectionStatus(str, Enum):
    """Canonical, machine-readable outcomes of a real connection test.

    These values are the stable vocabulary shared by connectors, the
    integrations manager API and the UI. A connector (or provider) never
    reports ``connected`` unless a real API endpoint answered successfully.
    """

    CONNECTED = "connected"
    AUTH_FAILED = "auth_failed"
    UNREACHABLE = "unreachable"
    INVALID_CONFIG = "invalid_config"
    API_UNAVAILABLE = "api_unavailable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """An immutable, structured outcome of a real connection test.

    Attributes:
        success: Whether the live connection succeeded.
        status: Canonical :class:`ConnectionStatus` value.
        message: Optional human-readable detail (never contains secrets).
        details: Optional machine-readable diagnostic details (no secrets).
    """

    success: bool
    status: ConnectionStatus
    message: str | None = None
    details: dict[str, str] | None = None
