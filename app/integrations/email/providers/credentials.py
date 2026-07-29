"""Reusable OAuth client configuration for email providers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OAuthClientCredentials:
    """OAuth client settings supplied by application configuration.

    The application composition root is responsible for loading these values
    from its configuration or secret manager; providers never embed secrets.
    """

    client_id: str
    client_secret: str | None = None
    redirect_uri: str | None = None
    scopes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.client_id, str) or not self.client_id.strip():
            raise ValueError("client_id is required")
        if self.client_secret is not None and not self.client_secret.strip():
            raise ValueError("client_secret must be non-empty when provided")
        if self.redirect_uri is not None and not self.redirect_uri.strip():
            raise ValueError("redirect_uri must be non-empty when provided")
        if any(not isinstance(scope, str) or not scope.strip() for scope in self.scopes):
            raise ValueError("scopes must contain non-empty strings")

        object.__setattr__(self, "client_id", self.client_id.strip())
        object.__setattr__(self, "client_secret", self.client_secret.strip() if self.client_secret else None)
        object.__setattr__(self, "redirect_uri", self.redirect_uri.strip() if self.redirect_uri else None)
        object.__setattr__(self, "scopes", tuple(scope.strip() for scope in self.scopes))
