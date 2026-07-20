"""Tests for the GoalOS universal integration framework."""

from __future__ import annotations

import types

import pytest

from app.integrations import (
    BaseConnector,
    ConnectorHealth,
    ConnectorHealthStatus,
    ConnectorLoader,
    ConnectorRegistry,
)


class ExampleConnector(BaseConnector):
    """Concrete connector used to verify the framework lifecycle."""

    def __init__(self) -> None:
        super().__init__(name="example", description="Example connector")

    def connect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED))

    def health_check(self) -> ConnectorHealth:
        return self._set_health(ConnectorHealth(self.status))

    def get_capabilities(self) -> tuple[str, ...]:
        return ("read", "write")


def test_base_connector_is_abstract() -> None:
    with pytest.raises(TypeError):
        BaseConnector(name="base", description="Abstract")


def test_connector_registry_manages_independent_connector_instances() -> None:
    registry = ConnectorRegistry()
    connector = ExampleConnector()

    registry.register(connector)

    assert registry.list_connectors() == ("example",)
    assert registry.get_connector(" example ") is connector
    assert registry.unregister("example") is connector
    assert registry.get_connector("example") is None


def test_connector_health_and_connection_lifecycle() -> None:
    connector = ExampleConnector()

    assert connector.status is ConnectorHealthStatus.DISCONNECTED
    assert connector.is_connected() is False

    connector.connect()
    health = connector.health_check()

    assert health.is_healthy is True
    assert connector.is_connected() is True
    assert connector.get_capabilities() == ("read", "write")

    connector.disconnect()
    assert connector.status is ConnectorHealthStatus.DISCONNECTED


def test_connector_loader_discovers_instantiates_and_initializes_connectors() -> None:
    module = types.ModuleType("test_connectors")

    class DiscoveredConnector(ExampleConnector):
        pass

    DiscoveredConnector.__module__ = module.__name__
    module.DiscoveredConnector = DiscoveredConnector
    loader = ConnectorLoader()

    assert loader.discover_connectors(module) == ("DiscoveredConnector",)
    loaded_connectors = loader.load_connectors()

    assert set(loaded_connectors) == {"example"}
    assert loaded_connectors["example"].is_initialized is True
    assert loader.get_connector("example") is loaded_connectors["example"]
