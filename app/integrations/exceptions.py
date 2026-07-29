"""Exception hierarchy for GoalOS integrations."""


class ConnectorError(Exception):
    """Base exception for connector failures."""


class ConnectionError(ConnectorError):
    """Raised when a connector cannot establish or maintain a connection."""


class AuthenticationError(ConnectionError):
    """Raised when connector authentication is missing, invalid, or expired."""


class ConfigurationError(ConnectorError):
    """Raised when a connector has invalid or incomplete configuration."""


class ConnectorUnavailableError(ConnectorError):
    """Raised when a requested connector is unavailable to the runtime."""
