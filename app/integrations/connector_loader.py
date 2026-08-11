"""Automatic connector discovery and lifecycle management."""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Mapping
from types import MappingProxyType, ModuleType
from typing import TypeAlias

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_registry import ConnectorRegistry

logger = logging.getLogger(__name__)

ConnectorClass: TypeAlias = type[BaseConnector]


class ConnectorLoader:
    """Discover, instantiate, and initialize connectors for one runtime."""

    def __init__(self, registry: ConnectorRegistry | None = None) -> None:
        """Create a loader with an injected registry when desired."""

        self.registry = registry or ConnectorRegistry()
        self._discovered_connector_classes: dict[str, ConnectorClass] = {}
        self._loaded_connectors: dict[str, BaseConnector] = {}

    @property
    def loaded_connectors(self) -> Mapping[str, BaseConnector]:
        """Expose an immutable snapshot of initialized connector instances."""

        return MappingProxyType(dict(self._loaded_connectors))

    def discover_connectors(
        self, package: ModuleType | str = "app.integrations"
    ) -> tuple[str, ...]:
        """Discover concrete connector classes contained by a package."""

        package_module = importlib.import_module(package) if isinstance(package, str) else package
        modules = [package_module]
        if hasattr(package_module, "__path__"):
            modules.extend(
                importlib.import_module(module.name)
                for module in pkgutil.walk_packages(
                    package_module.__path__, f"{package_module.__name__}."
                )
                if not module.name.rsplit(".", 1)[-1].startswith("_")
            )

        for module in modules:
            for _, connector_class in inspect.getmembers(module, inspect.isclass):
                if (
                    connector_class is BaseConnector
                    or not issubclass(connector_class, BaseConnector)
                    or inspect.isabstract(connector_class)
                    or connector_class.__module__ != module.__name__
                ):
                    continue
                self._discovered_connector_classes.setdefault(
                    connector_class.__name__, connector_class
                )

        discovered = tuple(sorted(self._discovered_connector_classes))
        logger.debug("Discovered GoalOS connectors: %s", discovered)
        return discovered

    def load_connectors(self) -> Mapping[str, BaseConnector]:
        """Instantiate and initialize all discovered and registered connectors."""

        for connector_class in self._discovered_connector_classes.values():
            connector = connector_class()
            if self.registry.get_connector(connector.name) is None:
                self.registry.register(connector)

        for name, connector in self.registry.snapshot().items():
            connector.initialize()
            self._loaded_connectors[name] = connector
            logger.info("Initialized GoalOS connector '%s'", name)

        return self.loaded_connectors

    def get_connector(self, name: str) -> BaseConnector | None:
        """Return a loaded connector by runtime name."""

        return self._loaded_connectors.get(name.strip())
