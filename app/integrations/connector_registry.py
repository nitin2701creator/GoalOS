"""Instance registry for GoalOS integration connectors."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from types import MappingProxyType

from app.integrations.base_connector import BaseConnector

logger = logging.getLogger(__name__)


class ConnectorRegistry:
    """Own connector instances for one runtime composition root."""

    def __init__(self) -> None:
        """Create an empty registry without process-wide mutable state."""

        self._connectors: dict[str, BaseConnector] = {}

    def register(self, connector: BaseConnector) -> None:
        """Register a connector under its stable name."""

        if not isinstance(connector, BaseConnector):
            raise TypeError("connector must inherit BaseConnector")
        name = self._normalize_name(connector.name)
        if name in self._connectors:
            raise ValueError(f"Connector already registered: {name}")
        self._connectors[name] = connector
        logger.debug("Registered GoalOS connector '%s'", name)

    def unregister(self, name: str) -> BaseConnector | None:
        """Remove and return a connector, if registered."""

        connector = self._connectors.pop(self._normalize_name(name), None)
        if connector is not None:
            logger.debug("Unregistered GoalOS connector '%s'", connector.name)
        return connector

    def list_connectors(self) -> tuple[str, ...]:
        """Return registered connector names in deterministic order."""

        return tuple(sorted(self._connectors))

    def get_connector(self, name: str) -> BaseConnector | None:
        """Return a connector by name, if it is registered."""

        return self._connectors.get(self._normalize_name(name))

    def snapshot(self) -> Mapping[str, BaseConnector]:
        """Return an immutable snapshot of registered connectors."""

        return MappingProxyType(dict(self._connectors))

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Normalize a connector registry key."""

        if not isinstance(name, str) or not (normalized_name := name.strip()):
            raise ValueError("connector name is required")
        return normalized_name
