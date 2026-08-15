"""Tests for the shared Google OAuth token service.

Covers: missing configuration honesty, successful refresh-token exchange
with in-memory caching, distinct authentication-failure and rate-limit
handling, malformed token responses, and legacy env var fallbacks. Never
touches the real Google token endpoint.
"""

from __future__ import annotations

import json

import pytest

from app.integrations.exceptions import AuthenticationError, RateLimitError
from app.integrations.google_auth import GoogleOAuthTokenProvider
from app.integrations.http_client import HttpClient
from tests.integration_helpers import FakeResponse

_GOOGLE_ENV = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "GOOGLE_REFRESH_TOKEN",
    "GOALOS_GMAIL_CLIENT_ID",
    "GOALOS_GMAIL_CLIENT_SECRET",
    "GOALOS_GMAIL_REFRESH_TOKEN",
)


def _clear_google_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GOOGLE_ENV:
        monkeypatch.delenv(name, raising=False)


def _token_opener(payload: dict, status: int = 200):
    def opener(request, timeout=None) -> FakeResponse:
        return FakeResponse(
            json.dumps(payload).encode(), str(request.full_url), status=status, content_type="application/json"
        )

    return opener


def _provider(monkeypatch: pytest.MonkeyPatch, opener=None, **kwargs) -> GoogleOAuthTokenProvider:
    return GoogleOAuthTokenProvider(
        client=HttpClient(opener=opener),
        client_id="client-id",
        client_secret="client-secret",
        refresh_token="refresh-token",
        **kwargs,
    )


def test_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    provider = GoogleOAuthTokenProvider()
    assert not provider.is_configured
    assert "GOOGLE_CLIENT_ID" in provider.missing_configuration()
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        provider.get_token()


def test_successful_token_exchange_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    calls: list[str] = []

    def opener(request, timeout=None) -> FakeResponse:
        calls.append(str(request.full_url))
        return FakeResponse(
            json.dumps({"access_token": "access-1", "expires_in": 3600}).encode(),
            str(request.full_url),
            content_type="application/json",
        )

    provider = _provider(monkeypatch, opener)
    assert provider.is_configured

    token = provider.get_token()
    assert token == "access-1"
    # Second call is served from the in-memory cache (no new request).
    assert provider.get_token() == "access-1"
    assert len(calls) == 1


def test_token_refreshes_after_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    import time

    calls: list[str] = []

    def opener(request, timeout=None) -> FakeResponse:
        calls.append(str(request.full_url))
        return FakeResponse(
            json.dumps({"access_token": f"token-{len(calls)}", "expires_in": 1}).encode(),
            str(request.full_url),
            content_type="application/json",
        )

    provider = _provider(monkeypatch, opener)
    provider.get_token()
    # Force the cache to expire, then verify a refresh happens.
    provider._expires_at = time.time() - 1
    assert provider.get_token() == "token-2"
    assert len(calls) == 2


def test_auth_failure_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    provider = _provider(
        monkeypatch,
        _token_opener({"error": "invalid_grant"}, status=401),
    )
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        provider.get_token()


def test_rate_limit_is_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    provider = _provider(monkeypatch, _token_opener({}, status=429))
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        provider.get_token()


def test_invalid_token_response_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)

    def opener(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    provider = _provider(monkeypatch, opener)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        provider.get_token()


def test_no_access_token_raises_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    provider = _provider(monkeypatch, _token_opener({"refresh_token": "new"}))
    with pytest.raises(AuthenticationError, match="no access token"):
        provider.get_token()


def test_legacy_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOALOS_GMAIL_CLIENT_ID", "legacy-id")
    monkeypatch.setenv("GOALOS_GMAIL_CLIENT_SECRET", "legacy-secret")
    monkeypatch.setenv("GOALOS_GMAIL_REFRESH_TOKEN", "legacy-refresh")
    provider = GoogleOAuthTokenProvider(client=HttpClient())
    assert provider.is_configured
    assert provider.client_id == "legacy-id"
    assert provider.refresh_token == "legacy-refresh"


def test_canonical_env_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_google_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "canonical-id")
    monkeypatch.setenv("GOALOS_GMAIL_CLIENT_ID", "legacy-id")
    provider = GoogleOAuthTokenProvider(client=HttpClient())
    assert provider.client_id == "canonical-id"
