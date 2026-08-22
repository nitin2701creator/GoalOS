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
    """Result of a connection test."""
    success: bool
    message: str
    details: dict = field(default_factory=dict)


@dataclass
class OAuthConfig:
    """OAuth configuration for a provider."""
    auth_url: str
    token_url: str
    scopes: list[str]
    redirect_uri: str


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

    def mask_value(self, key: str, value: str) -> str:
        """Return a masked version of a credential value for display."""
        if not value:
            return ""
        if len(value) < 8:
            return "•" * len(value)
        return value[:4] + "•" * (len(value) - 8) + value[-4:]
