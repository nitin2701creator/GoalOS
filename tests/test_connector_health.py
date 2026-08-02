"""Tests for aggregate connector health checks."""

from __future__ import annotations

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth
from app.integrations.connector_registry import ConnectorRegistry


class StubConnector(BaseConnector):
    """Connector whose health result is controlled by a test."""

    def __init__(self, name: str, health_result: bool | Exception) -> None:
        self.name = name
        self.health_result = health_result

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def health(self) -> bool:
        if isinstance(self.health_result, Exception):
            raise self.health_result
        return self.health_result


def test_check_all_reports_a_healthy_connector() -> None:
    registry = ConnectorRegistry()
    registry.register(StubConnector("calendar", True))

    assert ConnectorHealth(registry).check_all() == {"calendar": True}


def test_check_all_reports_an_unhealthy_connector() -> None:
    registry = ConnectorRegistry()
    registry.register(StubConnector("calendar", False))

    assert ConnectorHealth(registry).check_all() == {"calendar": False}


def test_check_all_records_failure_and_continues_after_health_exception() -> None:
    registry = ConnectorRegistry()
    registry.register(StubConnector("broken", RuntimeError("offline")))
    registry.register(StubConnector("calendar", True))

    assert ConnectorHealth(registry).check_all() == {"broken": False, "calendar": True}
