"""Reusable OAuth authentication adapter for email providers."""

from __future__ import annotations

from typing import Protocol

from app.integrations.email.authentication import OAuthAuthenticator
from app.integrations.email.config import EmailConfig
from app.integrations.email.providers.credentials import OAuthClientCredentials
from app.integrations.email.providers.token_store import (
    InMemoryTokenStore,
    OAuthToken,
    TokenStore,
)


class OAuthAuthorizationClient(Protocol):
    """Provider SDK adapter responsible for the interactive/token-refresh flow."""

    def authorize(
        self, credentials: OAuthClientCredentials, existing_token: OAuthToken | None
    ) -> OAuthToken: ...


class UnavailableOAuthAuthorizationClient:
    """Default adapter that makes missing SDK/configuration explicit."""

    def authorize(
        self, credentials: OAuthClientCredentials, existing_token: OAuthToken | None
    ) -> OAuthToken:
        raise NotImplementedError("OAuth authorization client has not been configured")


class ConfiguredOAuthAuthenticator(OAuthAuthenticator):
    """Authenticate with injected OAuth configuration and SDK adapter."""

    def __init__(
        self,
        credentials: OAuthClientCredentials | None = None,
        authorization_client: OAuthAuthorizationClient | None = None,
        token_store: TokenStore | None = None,
    ) -> None:
        self.credentials = credentials
        self.authorization_client = authorization_client or UnavailableOAuthAuthorizationClient()
        self.token_store = token_store or InMemoryTokenStore()

    def authenticate(self, config: EmailConfig) -> None:
        if self.credentials is None:
            raise RuntimeError("OAuth credentials must be supplied through provider configuration")
        token = self.authorization_client.authorize(
            self.credentials, self.token_store.load(config.provider)
        )
        self.token_store.save(config.provider, token)
