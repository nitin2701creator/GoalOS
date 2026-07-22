"""Small, replaceable persistence seam for OAuth access tokens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OAuthToken:
    """A token value returned by an OAuth authorization flow."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None


class TokenStore(Protocol):
    """Persistence contract; production code may back this with a vault."""

    def load(self, provider: str) -> OAuthToken | None: ...

    def save(self, provider: str, token: OAuthToken) -> None: ...


class InMemoryTokenStore:
    """Non-persistent token store suitable for tests and local composition."""

    def __init__(self) -> None:
        self._tokens: dict[str, OAuthToken] = {}

    def load(self, provider: str) -> OAuthToken | None:
        return self._tokens.get(provider)

    def save(self, provider: str, token: OAuthToken) -> None:
        self._tokens[provider] = token
