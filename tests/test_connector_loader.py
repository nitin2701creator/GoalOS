"""Tests for dynamic integration connector loading."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_loader import ConnectorLoader
from app.integrations.connector_registry import ConnectorRegistry


def _connector_module(name: str, class_name: str, connector_name: str) -> ModuleType:
    """Create an importable-looking module containing one connector class."""

    module = ModuleType(name)
    exec(
        f'''class {class_name}(BaseConnector):
    def __init__(self):
        self.name = "{connector_name}"

    def connect(self):
        pass

    def disconnect(self):
        pass

    def health(self):
        pass
''',
        {"BaseConnector": BaseConnector, "__name__": name},
        module.__dict__,
    )
    return module


def test_discover_connectors_imports_modules_and_finds_concrete_classes(monkeypatch) -> None:
    package = ModuleType("test_connectors")
    package.__path__ = []  # type: ignore[attr-defined]
    connector_module = _connector_module(
        "test_connectors.calendar", "CalendarConnector", "calendar"
    )
    imported_modules = {
        "test_connectors": package,
        "test_connectors.calendar": connector_module,
    }

    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: imported_modules[name],
    )
    monkeypatch.setattr(
        pkgutil,
        "walk_packages",
        lambda _path, _prefix: [pkgutil.ModuleInfo(None, "test_connectors.calendar", False)],
    )

    assert ConnectorLoader().discover_connectors("test_connectors") == ("CalendarConnector",)


def test_load_connectors_instantiates_and_registers_discovered_connectors() -> None:
    registry = ConnectorRegistry()
    loader = ConnectorLoader(registry)
    module = _connector_module("test_connectors", "DriveConnector", "drive")

    loader.discover_connectors(module)
    loaded = loader.load_connectors()

    assert set(loaded) == {"drive"}
    assert isinstance(loaded["drive"], BaseConnector)
    assert registry.get_connector("drive") is loaded["drive"]


def test_load_connectors_preserves_an_already_registered_connector() -> None:
    registry = ConnectorRegistry()
    existing = _connector_module("existing", "ExistingConnector", "drive").ExistingConnector()
    registry.register(existing)
    loader = ConnectorLoader(registry)
    loader.discover_connectors(_connector_module("test_connectors", "DriveConnector", "drive"))

    loaded = loader.load_connectors()

    assert loaded["drive"] is existing
