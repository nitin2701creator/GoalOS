"""Google OAuth interactive web-flow primitives.

These helpers build the Google consent URL and exchange the returned
authorization code for tokens at ``oauth2.googleapis.com/token`` using the
shared HTTP client — the same transport, error mapping, and secrecy rules
as the rest of the Google integrations. The refresh token obtained here
is handed to the service layer, which persists it and makes it available
to the existing connectors through the ``GOOGLE_REFRESH_TOKEN``
environment variable; it is never logged and never returned by an API
response.

Stable error mapping (mirrors ``app.integrations.google_auth``):

- token endpoint HTTP 400/401/403 → :class:`AuthenticationError`
  (``AUTHENTICATION_FAILED``)
- token endpoint HTTP 429 → :class:`RateLimitError` (``RATE_LIMITED``)
- any other upstream failure or malformed body → :class:`ConnectorError`
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from app.integrations.exceptions import (
    AuthenticationError,
    ConnectorError,
    RateLimitError,
)
from app.integrations.http_client import HttpStatusError

AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: The scopes the three Google connectors require. gmail.modify covers the
#: Gmail REST service, calendar the Calendar connector, drive.file the
#: Drive connector. One consent grant covers all three integrations.
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
)

#: How long an authorization ``state`` remains valid (in seconds).
STATE_TTL_SECONDS = 600

#: In-memory pending authorization states -> expiry timestamps. The app
#: runs as a single uvicorn process per container, so an in-memory store
#: is sufficient for the authorize -> callback round trip.
_pending_states: dict[str, float] = {}


def create_state() -> str:
    """Generate a fresh CSRF ``state`` and register it with a TTL."""
    state = secrets.token_urlsafe(32)
    _pending_states[state] = time.time() + STATE_TTL_SECONDS
    return state


def consume_state(state: str) -> bool:
    """Validate and consume a callback ``state``.

    Returns ``True`` exactly once per generated state; expired, unknown,
    or already-consumed states return ``False`` (the callback is refused).
    """
    expiry = _pending_states.pop(state, None)
    if expiry is None:
        return False
    return time.time() <= expiry


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    scopes: list[str] | tuple[str, ...],
    state: str,
    *,
    access_type: str = "offline",
    prompt: str = "consent",
) -> str:
    """Build the Google consent URL for the GoalOS OAuth web flow.

    ``access_type=offline`` is required so Google returns a refresh
    token; ``prompt=consent`` forces a fresh consent so a new refresh
    token is issued on every grant (the connectors need one to operate
    unattended).
    """
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": access_type,
        "prompt": prompt,
        "state": state,
    }
    return f"{AUTHORIZE_ENDPOINT}?{urlencode(params)}"


def exchange_code(
    client: Any,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
) -> dict[str, Any]:
    """Exchange an authorization code for OAuth tokens.

    Args:
        client: The shared :class:`HttpClient` (injectable for tests).

    Returns:
        A safe dict containing the refresh token and granted scopes —
        never the client secret, and never an access token.

    Raises:
        AuthenticationError: Google rejected the code (or returned no
            refresh token).
        RateLimitError: Google's token endpoint reported HTTP 429.
        ConnectorError: Any other upstream or malformed-response failure.
    """
    body = (
        "grant_type=authorization_code"
        f"&client_id={client_id}"
        f"&client_secret={client_secret}"
        f"&redirect_uri={redirect_uri}"
        f"&code={code}"
    )
    try:
        response = client.fetch(
            TOKEN_ENDPOINT,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=body.encode(),
        )
    except HttpStatusError as exc:
        _raise_token_error(int(exc.status), exc.url)

    status = int(getattr(response, "status", 200) or 200)
    url = getattr(response, "url", TOKEN_ENDPOINT)
    if status in (400, 401, 403):
        raise AuthenticationError(
            f"AUTHENTICATION_FAILED: Google rejected the authorization code "
            f"(HTTP {status} at {url})"
        )
    if status == 429:
        raise RateLimitError(
            f"RATE_LIMITED: Google token endpoint returned HTTP 429 at {url}"
        )
    if status >= 400:
        raise ConnectorError(
            f"Google token endpoint error: HTTP {status} at {url}"
        )

    try:
        payload = json.loads(response.text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ConnectorError(
            "invalid response from Google token endpoint: "
            "response body is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ConnectorError(
            "invalid response from Google token endpoint: expected a JSON object"
        )
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise AuthenticationError(
            "AUTHENTICATION_FAILED: Google token endpoint returned no refresh token"
        )
    scopes = [part for part in str(payload.get("scope") or "").split() if part]
    return {"refresh_token": str(refresh_token), "scopes": scopes}


def _raise_token_error(status: int, url: str) -> None:
    """Map a raised token-endpoint status to the stable GoalOS errors."""
    if status in (400, 401, 403):
        raise AuthenticationError(
            f"AUTHENTICATION_FAILED: Google rejected the authorization code "
            f"(HTTP {status} at {url})"
        )
    if status == 429:
        raise RateLimitError(
            f"RATE_LIMITED: Google token endpoint returned HTTP 429 at {url}"
        )
    raise ConnectorError(f"Google token endpoint error: HTTP {status} at {url}")
