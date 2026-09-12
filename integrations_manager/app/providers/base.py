"""Base integration provider abstraction.

All platform providers implement this interface.
Add new integrations by subclassing BaseProvider.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field


@dataclass
class IntegrationInfo:
    """Metadata about an integration provider."""
    slug: str
    name: str
    description: str
    icon: str  # icon class or emoji
    auth_type: str  # "api_key" | "oauth2"
    credential_fields: list[dict] = field(default_factory=list)
    oauth_scopes: list[str] = field(default_factory=list)
    oauth_auth_url: str = ""
    oauth_token_url: str = ""


@dataclass
class TestResult:
    """Result of a connection test.

    Attributes:
        success: Whether the live connection succeeded.
        message: Human-readable outcome (never contains secrets).
        details: Optional machine-readable diagnostics (no secrets).
        status: Canonical connection status vocabulary used by the UI:
            ``connected``, ``auth_failed``, ``unreachable``,
            ``invalid_config``, ``api_unavailable``, or ``error``. Empty
            strings are normalized by callers to ``connected``/``error``
            based on ``success``.
    """
    success: bool
    message: str
    details: dict = field(default_factory=dict)
    status: str = ""


@dataclass
class OAuthConfig:
    """OAuth configuration for a provider."""
    auth_url: str
    token_url: str
    scopes: list[str]
    redirect_uri: str
    
    def get_auth_url(self, state: str, redirect_uri: str) -> str:
        """Construct the full OAuth authorization URL with state and redirect URI."""
        return f"{self.auth_url}?response_type=code&client_id={redirect_uri.split('/')[2]}&redirect_uri={redirect_uri}&scope={' '.join(self.scopes)}&state={state}"


class BaseProvider(abc.ABC):
    """Abstract base class for integration providers."""

    @abc.abstractmethod
    def info(self) -> IntegrationInfo:
        """Return metadata about this integration."""
        ...

    @abc.abstractmethod
    def get_credential_fields(self) -> list[dict]:
        """Return the credential fields this provider requires.

        Each dict has: key, label, type (text|password|url), required (bool).
        """
        ...

    @abc.abstractmethod
    def get_oauth_config(self) -> OAuthConfig | None:
        """Return OAuth config if this provider uses OAuth, else None."""
        ...

    @abc.abstractmethod
    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        """Test the connection with the given credentials.

        credentials: decrypted credential key-value pairs.
        """
        ...

    @abc.abstractmethod
    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        """Return connected account information (non-secret)."""
        ...
        
    def get_connection_state(self, credentials: dict[str, str]) -> str:
        """Return the connection state for this integration.

        Default implementation used by API-key providers: ``not_configured``
        when no credentials are stored, ``configured`` otherwise. OAuth
        providers already override this to distinguish ``available``,
        ``browser_auth_required``, ``connected``, and ``error``.
        """
        if not credentials:
            return 'not_configured'
        return 'configured'
        
    def get_connection_state_from_credentials(self, credentials: dict[str, str]) -> str:
        """Default implementation for connection state.
        
        Override in subclasses for custom logic.
        """
        access_token = credentials.get('access_token', '')
        refresh_token = credentials.get('refresh_token', '')
        
        if not access_token and not refresh_token:
            return 'browser_auth_required'
        return 'available'

    def mask_value(self, key: str, value: str) -> str:
        """Return a masked version of a credential value for display."""
        if not value:
            return ""
        if len(value) < 8:
            return "•" * len(value)
        return value[:4] + "•" * (len(value) - 8) + value[-4:]
