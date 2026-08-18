"""Google OAuth web-flow service.

Orchestrates the interactive Google OAuth consent flow that mints the
refresh token the Gmail, Calendar, and Drive connectors run on:

1. ``authorize_url`` builds the Google consent URL from the configured
   ``GOOGLE_CLIENT_ID`` / ``GOOGLE_REDIRECT_URI`` (redirect URI comes
   from the environment — never hard-coded).
2. ``handle_callback`` validates the CSRF ``state``, exchanges the
   authorization code at the token endpoint, persists the refresh token
   in the dedicated ``google_oauth_credentials`` table, and writes it
   into the process environment as ``GOOGLE_REFRESH_TOKEN`` so every
   existing Google connector picks it up immediately — Gmail, Calendar,
   and Drive all share this one credential set.
3. ``load_into_environment`` re-hydrates the environment from the
   database at application startup, so a token granted through the web
   flow survives restarts without touching the operator's ``.env``.

Secrecy contract: the client secret, refresh token, and access tokens
are never logged, never persisted outside the dedicated credential table
(never the ``integrations`` registry), and never included in responses.
Failure messages carry stable codes (``AUTHENTICATION_FAILED``,
``RATE_LIMITED``) and the *names* of missing environment variables — no
values.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.exceptions import ConfigurationError
from app.integrations.google_oauth_flow import (
    DEFAULT_SCOPES,
    build_authorize_url,
    consume_state,
    create_state,
    exchange_code,
)
from app.integrations.http_client import HttpClient
from app.repositories.google_oauth_repository import GoogleOAuthRepository

#: Canonical environment variable names for the Google OAuth web flow.
REQUIRED_ENV_VARS: tuple[str, ...] = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
)

#: Legacy Gmail-only fallbacks accepted for client id/secret (matching
#: ``app.integrations.google_auth``). The redirect URI has no legacy name.
_LEGACY_ENV_VARS: dict[str, str] = {
    "GOOGLE_CLIENT_ID": "GOALOS_GMAIL_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET": "GOALOS_GMAIL_CLIENT_SECRET",
}


class GoogleOAuthService:
    """Build the consent URL and complete the callback for Google OAuth."""

    PROVIDER = "google"
    #: Environment variable the stored refresh token is hydrated into.
    REFRESH_TOKEN_ENV = "GOOGLE_REFRESH_TOKEN"

    def __init__(self, db: Session, *, client: HttpClient | None = None) -> None:
        self.db = db
        self.repository = GoogleOAuthRepository(db)
        self.client = client or HttpClient()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @classmethod
    def configuration(cls) -> dict[str, str]:
        """Return the configured OAuth values (never secrets beyond what
        the operator set; only client id, secret, and redirect URI).

        Raises:
            ConfigurationError: When any required variable is absent —
                the message lists only the missing variable names.
        """
        values = {name: cls._env(name) for name in REQUIRED_ENV_VARS}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ConfigurationError(
                "Google OAuth is not configured (missing environment "
                f"variables: {', '.join(missing)})"
            )
        return {name: str(value) for name, value in values.items()}

    @staticmethod
    def _env(name: str) -> str | None:
        """Read one env var, preferring the canonical name over legacy."""
        candidates = (name, _LEGACY_ENV_VARS.get(name))
        for candidate in candidates:
            if not candidate:
                continue
            value = os.environ.get(candidate)
            if value and value.strip():
                return value.strip()
        return None

    # ------------------------------------------------------------------
    # Flow
    # ------------------------------------------------------------------
    def authorize_url(self, scope: str | None = None, state: str | None = None) -> str:
        """Build the Google consent URL for a browser redirect.

        Args:
            scope: Optional space-separated scope override; defaults to
                the shared Gmail + Calendar + Drive scope set.
            state: Optional caller-supplied CSRF state; a fresh state is
                generated and registered when omitted.
        """
        cfg = self.configuration()
        scopes = scope.split() if scope and scope.strip() else list(DEFAULT_SCOPES)
        return build_authorize_url(
            cfg["GOOGLE_CLIENT_ID"],
            cfg["GOOGLE_REDIRECT_URI"],
            scopes,
            state or create_state(),
        )

    def handle_callback(self, code: str, state: str) -> dict[str, Any]:
        """Complete the OAuth flow: validate state, exchange the code,
        persist and activate the refresh token.

        Raises:
            ConfigurationError: The CSRF state is invalid/expired (the
                callback is refused).
            AuthenticationError / RateLimitError / ConnectorError: The
                token exchange failed (propagated from the flow module).

        Returns:
            A safe summary (provider, scopes, configured) — never tokens.
        """
        if not state or not consume_state(state):
            raise ConfigurationError(
                "Google OAuth callback refused: invalid or expired state"
            )
        cfg = self.configuration()
        tokens = exchange_code(
            self.client,
            client_id=cfg["GOOGLE_CLIENT_ID"],
            client_secret=cfg["GOOGLE_CLIENT_SECRET"],
            redirect_uri=cfg["GOOGLE_REDIRECT_URI"],
            code=code,
        )
        self.repository.upsert(
            self.PROVIDER, tokens["refresh_token"], tokens["scopes"]
        )
        os.environ[self.REFRESH_TOKEN_ENV] = tokens["refresh_token"]
        return {
            "provider": self.PROVIDER,
            "scopes": tokens["scopes"],
            "configured": True,
        }

    def load_into_environment(self) -> bool:
        """Hydrate ``GOOGLE_REFRESH_TOKEN`` from the stored credential.

        Called at application startup so a token granted through the web
        flow keeps the existing connectors configured across restarts.
        Returns ``True`` when a token was loaded.
        """
        row = self.repository.get(self.PROVIDER)
        if row is None or not row.refresh_token:
            return False
        os.environ[self.REFRESH_TOKEN_ENV] = row.refresh_token
        return True
