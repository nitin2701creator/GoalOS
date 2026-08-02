"""Tests for the integration connector instance registry."""

from __future__ import annotations

import pytest

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_registry import ConnectorRegistry


class StubConnector(BaseConnector):
    """Minimal concrete connector for registry tests."""

    def __init__(self, name: str) -> None:
        self.name = name

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health(self) -> None:
        pass


def test_register_adds_connector_under_its_normalized_name() -> None:
    registry = ConnectorRegistry()
    connector = StubConnector(" email ")

    registry.register(connector)

    assert registry.get_connector("email") is connector


def test_unregister_returns_connector_and_removes_it() -> None:
    registry = ConnectorRegistry()
    connector = StubConnector("email")
    registry.register(connector)

    assert registry.unregister(" email ") is connector
    assert registry.get_connector("email") is None
    assert registry.unregister("email") is None


def test_get_connector_returns_registered_connector_or_none() -> None:
    registry = ConnectorRegistry()
    connector = StubConnector("email")
    registry.register(connector)

    assert registry.get_connector(" email ") is connector
    assert registry.get_connector("missing") is None


def test_list_connectors_returns_names_in_deterministic_order() -> None:
    registry = ConnectorRegistry()
    registry.register(StubConnector("zeta"))
    registry.register(StubConnector("alpha"))

    assert registry.list_connectors() == ("alpha", "zeta")


def test_register_rejects_duplicate_normalized_connector_name() -> None:
    registry = ConnectorRegistry()
    registry.register(StubConnector("email"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubConnector(" email "))
