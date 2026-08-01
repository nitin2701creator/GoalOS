"""Reusable health models for GoalOS integrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.connector_registry import ConnectorRegistry


class ConnectorHealthStatus(str, Enum):
    """Supported states reported by a connector."""

    HEALTHY = "Healthy"
    DISCONNECTED = "Disconnected"
    AUTHENTICATION_REQUIRED = "Authentication Required"
    ERROR = "Error"


@dataclass(frozen=True, slots=True, init=False)
class ConnectorHealth:
    """Represent a connector health report or check all registry connectors.

    Pass a :class:`ConnectorHealthStatus` to create an immutable report.  Pass
    a ``ConnectorRegistry`` to check every registered connector with
    :meth:`check_all`.
    """

    status: ConnectorHealthStatus | None
    message: str | None
    _registry: ConnectorRegistry | None = field(repr=False, compare=False)

    def __init__(
        self, status_or_registry: ConnectorHealthStatus | ConnectorRegistry, message: str | None = None
    ) -> None:
        """Create either a status report or a registry health checker."""

        from app.integrations.connector_registry import ConnectorRegistry

        if isinstance(status_or_registry, ConnectorRegistry):
            object.__setattr__(self, "status", None)
            object.__setattr__(self, "message", None)
            object.__setattr__(self, "_registry", status_or_registry)
            return

        object.__setattr__(self, "status", status_or_registry)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "_registry", None)

    @property
    def is_healthy(self) -> bool:
        """Return whether the connector is ready to serve requests."""

        return self.status is ConnectorHealthStatus.HEALTHY

    def check_all(self) -> dict[str, bool]:
        """Return health results for every connector in the supplied registry.

        A connector failure is isolated to that connector so all remaining
        connectors continue to be checked.
        """

        if self._registry is None:
            raise ValueError("a ConnectorRegistry is required to check connector health")

        results: dict[str, bool] = {}
        for name, connector in self._registry.snapshot().items():
            try:
                result = connector.health()
                results[name] = result.is_healthy if isinstance(result, ConnectorHealth) else bool(result)
            except Exception:
                results[name] = False
        return results
