"""Base lifecycle contract for GoalOS integration connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus


class BaseConnector(ABC):
    """Abstract foundation for a single external-system integration.

    Concrete connectors own provider-specific credentials and transport. The
    framework manages their identity, lifecycle, and health consistently.
    """

    name: str
    description: str

    def __init__(self, name: str, description: str) -> None:
        """Initialize connector metadata in a disconnected state."""

        self.name = self._require_text(name, "name")
        self.description = self._require_text(description, "description")
        self._status = ConnectorHealthStatus.DISCONNECTED
        self._initialized = False

    @property
    def status(self) -> ConnectorHealthStatus:
        """Return the most recently reported operational status."""

        return self._status

    @property
    def is_initialized(self) -> bool:
        """Return whether runtime initialization has completed."""

        return self._initialized

    def initialize(self) -> None:
        """Prepare local connector resources without opening a connection.

        Connection is intentionally explicit, so loading the runtime never
        triggers external authentication or network activity.
        """

        self._initialized = True

    @abstractmethod
    def connect(self) -> None:
        """Establish a connection to the external system."""

    @abstractmethod
    def disconnect(self) -> None:
        """Release any connection to the external system."""

    @abstractmethod
    def health_check(self) -> ConnectorHealth:
        """Return the connector's current health report."""

    @abstractmethod
    def get_capabilities(self) -> tuple[str, ...]:
        """Return stable capability names supported by this connector."""

    def is_connected(self) -> bool:
        """Return whether the connector currently reports a healthy connection."""

        return self.status is ConnectorHealthStatus.HEALTHY

    def _set_health(self, health: ConnectorHealth) -> ConnectorHealth:
        """Record and return a health report for use by subclasses."""

        self._status = health.status
        return health

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        """Normalize and validate required connector metadata."""

        if not isinstance(value, str) or not (normalized_value := value.strip()):
            raise ValueError(f"{field_name} is required")
        return normalized_value
