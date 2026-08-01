"""Base lifecycle contract for GoalOS integration connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus


class BaseConnector(ABC):
    """Provide the established connector lifecycle and health compatibility API.

    New connectors may implement :meth:`health`; existing connectors continue
    to implement :meth:`health_check`.  The default ``health`` adapter keeps
    both forms usable by the registry health checker.
    """

    name: str
    description: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Adapt legacy ``health_check`` implementations to ``health``."""

        super().__init_subclass__(**kwargs)
        if "health" not in cls.__dict__ and "health_check" in cls.__dict__:
            cls.health = BaseConnector._health_from_check

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
        """Prepare local resources without opening an external connection."""

        self._initialized = True

    @abstractmethod
    def connect(self) -> None:
        """Establish a connection to the external system."""

    @abstractmethod
    def disconnect(self) -> None:
        """Release any connection to the external system."""

    @abstractmethod
    def health(self) -> ConnectorHealth:
        """Return health using the established ``health_check`` contract."""

        return self.health_check()

    def _health_from_check(self) -> ConnectorHealth:
        """Concrete adapter installed for legacy ``health_check`` subclasses."""

        return self.health_check()

    def health_check(self) -> ConnectorHealth:
        """Return the current stored health for connectors using ``health``."""

        return ConnectorHealth(self.status)

    def get_capabilities(self) -> tuple[str, ...]:
        """Return stable capability names supported by this connector."""

        return ()

    def is_connected(self) -> bool:
        """Return whether the connector currently reports a healthy connection."""

        return self.status is ConnectorHealthStatus.HEALTHY

    def _set_health(self, health: ConnectorHealth) -> ConnectorHealth:
        """Record and return a health report for use by subclasses."""

        if health.status is not None:
            self._status = health.status
        return health

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        """Normalize and validate required connector metadata."""

        if not isinstance(value, str) or not (normalized_value := value.strip()):
            raise ValueError(f"{field_name} is required")
        return normalized_value
