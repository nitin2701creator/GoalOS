"""Universal integration framework for GoalOS connectors."""

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.connector_loader import ConnectorLoader
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ConnectorUnavailableError,
)

__all__ = [
    "AuthenticationError",
    "BaseConnector",
    "ConfigurationError",
    "ConnectionError",
    "ConnectorHealth",
    "ConnectorHealthStatus",
    "ConnectorLoader",
    "ConnectorRegistry",
    "ConnectorUnavailableError",
]
