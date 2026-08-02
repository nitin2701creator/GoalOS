"""Composition root for integration connector plugins."""

from __future__ import annotations

from types import ModuleType

from app.integrations.connector_health import ConnectorHealth
from app.integrations.connector_loader import ConnectorLoader
from app.integrations.connector_registry import ConnectorRegistry


class PluginManager:
    """Discover, register, and check integration connectors."""

    def __init__(self, connector_package: ModuleType | str = "app.integrations") -> None:
        self.connector_package = connector_package
        self.registry = ConnectorRegistry()
        self.loader = ConnectorLoader(self.registry)
        self.health = ConnectorHealth(self.registry)
        self.health_status: dict[str, bool] = {}

    def initialize(self) -> dict[str, bool]:
        """Discover connectors, register their instances, and check health."""

        self.loader.discover_connectors(self.connector_package)
        self.loader.load_connectors()
        self.health_status = self.health.check_all()
        return self.health_status
