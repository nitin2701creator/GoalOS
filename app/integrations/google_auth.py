"""Shared Google OAuth 2.0 credential/token service.

One reusable service exchanges a stored refresh token for short-lived
access tokens for the Gmail, Calendar, and Drive connectors. Access
tokens are cached in memory only (never in the database) and refreshed
when they expire. Tokens are never logged and never exposed in results.

Configuration is environment-driven:

- ``GOOGLE_CLIENT_ID``
- ``GOOGLE_CLIENT_SECRET``
- ``GOOGLE_REDIRECT_URI`` (used when granting the initial consent)
- ``GOOGLE_REFRESH_TOKEN``

For backward compatibility the legacy ``GOALOS_GMAIL_*`` variable names
are accepted as fallbacks.

Stable error mapping: invalid/expired credentials raise
:class:`AuthenticationError` carrying ``AUTHENTICATION_FAILED``, and the
token endpoint returning HTTP 429 raises :class:`RateLimitError` carrying
``RATE_LIMITED`` — never a fabricated token and never a leaked secret.
"""

from __future__ import annotations

import json
import logging
import time

from app.integrations.exceptions import AuthenticationError, RateLimitError
from app.integrations.http_client import HttpClient, HttpStatusError

logger = logging.getLogger(__name__)

_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: Canonical Google configuration variable names (env.example documents them).
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "GOOGLE_REFRESH_TOKEN",
)

#: Legacy Gmail-only variable names accepted as fallbacks.
_LEGACY_ENV_VARS: dict[str, str] = {
    "GOOGLE_CLIENT_ID": "GOALOS_GMAIL_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET": "GOALOS_GMAIL_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN": "GOALOS_GMAIL_REFRESH_TOKEN",
}


class GoogleOAuthTokenProvider:
    """Obtain and cache Google access tokens from a stored refresh token.

    Args:
        client: Shared HTTP client (tests inject a fake opener).
        client_id / client_secret / refresh_token: Explicit overrides;
            default to environment configuration.
        scope: OAuth scope this token is used for (metadata; the granted
            scopes come from the original consent, not the refresh grant).
    """

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        refresh_token: str | None = None,
        scope: str = "",
    ) -> None:
        self.client = client or HttpClient()
        self.client_id = client_id or self._env("GOOGLE_CLIENT_ID") or ""
        self.client_secret = client_secret or self._env("GOOGLE_CLIENT_SECRET") or ""
        self.refresh_token = refresh_token or self._env("GOOGLE_REFRESH_TOKEN") or ""
        self.scope = scope
        # In-memory cache only: never persisted, never logged.
        self._access_token: str | None = None
        self._expires_at: float | None = None

    @property
    def is_configured(self) -> bool:
        """Return whether a refresh token and client credentials are present."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def missing_configuration(self) -> tuple[str, ...]:
        """Return the canonical env var names still absent."""
        present = {
            "GOOGLE_CLIENT_ID": self.client_id,
            "GOOGLE_CLIENT_SECRET": self.client_secret,
            "GOOGLE_REDIRECT_URI": True,
            "GOOGLE_REFRESH_TOKEN": self.refresh_token,
        }
        return tuple(name for name, value in present.items() if not value)

    def get_token(self) -> str:
        """Return a valid access token, refreshing when expired or absent.

        Raises:
            AuthenticationError: Credentials are missing/invalid/expired
                (message carries ``AUTHENTICATION_FAILED``).
            RateLimitError: The token endpoint reported HTTP 429.
        """
        if not self.is_configured:
            missing = ", ".join(self.missing_configuration())
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: Google OAuth credentials are not "
                f"configured (missing: {missing})"
            )
        if self._access_token and self._expires_at and time.time() < self._expires_at:
            return self._access_token
        return self._refresh()

    def invalidate(self) -> None:
        """Drop the cached access token (forces a refresh on next use)."""
        self._access_token = None
        self._expires_at = None

    def _refresh(self) -> str:
        """Exchange the refresh token for a fresh access token."""
        body = (
            "grant_type=refresh_token"
            f"&client_id={self.client_id}"
            f"&client_secret={self.client_secret}"
            f"&refresh_token={self.refresh_token}"
        )
        try:
            response = self.client.fetch(
                _TOKEN_ENDPOINT,
                method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                body=body.encode(),
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status in (400, 401, 403):
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Google rejected the refresh "
                    f"token (HTTP {status} from {exc.url})"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Google token endpoint returned HTTP 429 "
                    f"at {exc.url}"
                ) from exc
            raise
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise AuthenticationError(
                "AUTHENTICATION_FAILED: Google token endpoint returned an "
                "invalid response"
            ) from exc
        token = payload.get("access_token")
        if not token:
            raise AuthenticationError(
                "AUTHENTICATION_FAILED: Google token endpoint returned no "
                "access token"
            )
        self._access_token = str(token)
        expires_in = payload.get("expires_in")
        try:
            ttl = max(0, int(expires_in) - 60) if expires_in is not None else 3000
        except (TypeError, ValueError):
            ttl = 3000
        self._expires_at = time.time() + ttl
        return self._access_token

    @staticmethod
    def _env(name: str) -> str | None:
        """Read one env var, preferring the canonical name over legacy names."""
        import os

        candidates = (name, _LEGACY_ENV_VARS.get(name))
        for candidate in candidates:
            if not candidate:
                continue
            value = os.environ.get(candidate)
            if value and value.strip():
                return value.strip()
        return None


def auth_headers(token_provider: GoogleOAuthTokenProvider) -> dict[str, str]:
    """Return the Authorization header for one Google API call."""
    return {"Authorization": f"Bearer {token_provider.get_token()}"}


def decode_error_payload(text: str) -> str:
    """Extract a short, safe error summary from a Google API error body."""
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:300]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if message:
                return str(message)[:300]
            return str(error.get("code") or error)[:300]
        if isinstance(error, str):
            return error[:300]
    return text[:300]
