"""Tests for the Google OAuth web-flow primitives.

Covers the consent URL builder, the CSRF state store, and the
authorization-code exchange (success, authentication failure, rate
limiting, upstream failure, malformed responses) — all against the fake
HTTP transport, never the real Google service.
"""

from __future__ import annotations

from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from app.integrations.exceptions import (
    AuthenticationError,
    ConnectorError,
    RateLimitError,
)
from app.integrations.google_oauth_flow import (
    AUTHORIZE_ENDPOINT,
    DEFAULT_SCOPES,
    TOKEN_ENDPOINT,
    build_authorize_url,
    consume_state,
    create_state,
    exchange_code,
)
from app.integrations.http_client import HttpClient
from tests.integration_helpers import FakeResponse

CLIENT_ID = "client-id-test"
CLIENT_SECRET = "client-secret-test"
REDIRECT_URI = "http://goalos.test:8000/api/v1/integrations/google/callback"
AUTH_CODE = "authorization-code-test"


class _TokenOpener:
    """Fake ``urlopen`` serving one scripted token-endpoint response."""

    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        self.body = body
        self.status = status

    def __call__(self, request, timeout=None):
        return FakeResponse(self.body, TOKEN_ENDPOINT, status=self.status)


class _RaisingOpener:
    """Fake ``urlopen`` that raises (simulates an HTTP 500 from urllib)."""

    def __call__(self, request, timeout=None):
        raise HTTPError(TOKEN_ENDPOINT, 500, "Internal Server Error", {}, None)


def _client(monkeypatch: pytest.MonkeyPatch, opener) -> HttpClient:
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    return HttpClient()


# ----------------------------------------------------------------------
# Consent URL
# ----------------------------------------------------------------------


def test_build_authorize_url_contains_required_params() -> None:
    """The consent URL carries every parameter Google needs."""
    url = build_authorize_url(CLIENT_ID, REDIRECT_URI, DEFAULT_SCOPES, "state-1")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTHORIZE_ENDPOINT
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-1"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == [" ".join(DEFAULT_SCOPES)]


def test_build_authorize_url_accepts_custom_scope() -> None:
    """A caller-supplied scope overrides the default scope set."""
    url = build_authorize_url(CLIENT_ID, REDIRECT_URI, ["https://example/read"], "s")
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == ["https://example/read"]


# ----------------------------------------------------------------------
# CSRF state
# ----------------------------------------------------------------------


def test_state_round_trip_consumes_once() -> None:
    """A generated state validates exactly once, then is consumed."""
    state = create_state()
    assert consume_state(state) is True
    # Replay is refused.
    assert consume_state(state) is False


def test_state_unknown_is_refused() -> None:
    """An unknown or forged state is never accepted."""
    assert consume_state("not-a-real-state") is False


def test_state_expired_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """An expired state is refused even if never consumed."""
    state = create_state()
    # Force expiry: rewind the registered expiry below now.
    monkeypatch.setattr("app.integrations.google_oauth_flow.time.time", lambda: 10**12)
    assert consume_state(state) is False


# ----------------------------------------------------------------------
# Code exchange
# ----------------------------------------------------------------------


def test_exchange_code_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A valid code returns the refresh token and granted scopes."""
    body = (
        b'{"access_token":"access-test","expires_in":3599,'
        b'"refresh_token":"refresh-test","scope":"https://www.googleapis.com/auth/calendar"'
        b"}"
    )
    client = _client(monkeypatch, _TokenOpener(body=body))

    tokens = exchange_code(
        client,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        code=AUTH_CODE,
    )

    assert tokens["refresh_token"] == "refresh-test"
    assert tokens["scopes"] == ["https://www.googleapis.com/auth/calendar"]


def test_exchange_code_rejects_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 401 from the token endpoint maps to AUTHENTICATION_FAILED."""
    client = _client(
        monkeypatch, _TokenOpener(body=b'{"error":"invalid_grant"}', status=401)
    )
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        exchange_code(
            client,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            code="bad-code",
        )


def test_exchange_code_maps_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 429 from the token endpoint maps to RATE_LIMITED."""
    client = _client(
        monkeypatch, _TokenOpener(body=b'{"error":"rate_limit_exceeded"}', status=429)
    )
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        exchange_code(
            client,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            code=AUTH_CODE,
        )


def test_exchange_code_maps_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An HTTP 500 from the token endpoint maps to ConnectorError."""
    client = _client(monkeypatch, _RaisingOpener())
    with pytest.raises(ConnectorError):
        exchange_code(
            client,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            code=AUTH_CODE,
        )


def test_exchange_code_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-JSON 200 body is an invalid response, never a success."""
    client = _client(monkeypatch, _TokenOpener(body=b"not json at all", status=200))
    with pytest.raises(ConnectorError, match="not valid JSON"):
        exchange_code(
            client,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            code=AUTH_CODE,
        )


def test_exchange_code_missing_refresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 without a refresh token is refused (offline access missing)."""
    client = _client(
        monkeypatch, _TokenOpener(body=b'{"access_token":"access-test"}', status=200)
    )
    with pytest.raises(AuthenticationError, match="no refresh token"):
        exchange_code(
            client,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            code=AUTH_CODE,
        )


def test_exchange_code_never_leaks_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Error messages never contain the client secret or auth code."""
    client = _client(
        monkeypatch, _TokenOpener(body=b'{"error":"invalid_grant"}', status=401)
    )
    with pytest.raises(AuthenticationError) as excinfo:
        exchange_code(
            client,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            code=AUTH_CODE,
        )
    message = str(excinfo.value)
    assert CLIENT_SECRET not in message
    assert AUTH_CODE not in message
