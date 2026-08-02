"""Tests for integration plugin composition."""

from __future__ import annotations

from types import ModuleType

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth
from app.integrations.connector_loader import ConnectorLoader
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.plugin_manager import PluginManager


def _connector_module() -> ModuleType:
    module = ModuleType("test_plugins")
    exec(
        '''class HealthyConnector(BaseConnector):
    def __init__(self):
        self.name = "healthy"

    def connect(self):
        pass

    def disconnect(self):
        pass

    def health(self):
        return True
''',
        {"BaseConnector": BaseConnector, "__name__": module.__name__},
        module.__dict__,
    )
    return module


def test_plugin_manager_creates_integration_components() -> None:
    manager = PluginManager(_connector_module())

    assert isinstance(manager.registry, ConnectorRegistry)
    assert isinstance(manager.loader, ConnectorLoader)
    assert isinstance(manager.health, ConnectorHealth)
    assert manager.health_status == {}


def test_initialize_discovers_registers_and_checks_connectors() -> None:
    manager = PluginManager(_connector_module())

    health_status = manager.initialize()

    assert manager.registry.list_connectors() == ("healthy",)
    assert health_status == {"healthy": True}
    assert manager.health_status == health_status
