"""API tests for the Google OAuth web flow.

Exercises ``GET /api/v1/integrations/google/authorize`` and ``GET
/api/v1/integrations/google/callback`` end to end against the real FastAPI
app with an isolated SQLite database and the fake HTTP transport — the
token exchange never touches Google. Verifies persistence, environment
activation, and that no secret ever appears in a response.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app
from app.repositories.google_oauth_repository import GoogleOAuthRepository
from app.services.google_oauth_service import GoogleOAuthService
from tests.integration_helpers import FakeResponse

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
AUTHORIZE_PATH = "/api/v1/integrations/google/authorize"
CALLBACK_PATH = "/api/v1/integrations/google/callback"
REDIRECT_URI = "http://goalos.test:8000" + CALLBACK_PATH
CLIENT_ID = "client-id-test"
CLIENT_SECRET = "client-secret-test"
REFRESH_TOKEN = "refresh-token-test"
AUTH_CODE = "authorization-code-test"

DEFAULT_SCOPES = (
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive.file",
)


class _TokenOpener:
    """Fake ``urlopen`` serving one scripted token-endpoint response."""

    def __init__(self, body: bytes = b"", status: int = 200) -> None:
        self.body = body
        self.status = status

    def __call__(self, request, timeout=None):
        return FakeResponse(self.body, TOKEN_ENDPOINT, status=self.status)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB and configured Google credentials."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'oauth.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_get_db
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", REDIRECT_URI)
    with TestClient(app) as client:
        yield client, factory
    # The callback writes GOOGLE_REFRESH_TOKEN directly into the process
    # environment; remove it so it never leaks into other tests.
    os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
    app.dependency_overrides.clear()
    engine.dispose()


def _authorize_state(client: TestClient) -> str:
    """Run the authorize route and extract the generated CSRF state."""
    response = client.get(AUTHORIZE_PATH, follow_redirects=False)
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    return query["state"][0]


def _grant(
    client: TestClient,
    opener: _TokenOpener,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Run authorize -> callback against ``opener`` and return the state."""
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    return _authorize_state(client)


# ----------------------------------------------------------------------
# Authorize
# ----------------------------------------------------------------------


def test_authorize_redirects_to_google_consent(api) -> None:
    """The authorize route 307-redirects to Google with every param."""
    client, _ = api
    response = client.get(AUTHORIZE_PATH, follow_redirects=False)

    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://accounts.google.com/o/oauth2/v2/auth"
    )
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["state"]  # a fresh CSRF state is generated
    assert query["scope"] == [" ".join(DEFAULT_SCOPES)]
    # The redirect URI always points back at the GoalOS callback route.
    assert query["redirect_uri"][0].endswith(CALLBACK_PATH)


def test_authorize_accepts_custom_scope(api) -> None:
    """A scope query parameter overrides the default scope set."""
    client, _ = api
    response = client.get(
        AUTHORIZE_PATH, params={"scope": "https://www.googleapis.com/auth/calendar"},
        follow_redirects=False,
    )
    assert response.status_code == 307
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["https://www.googleapis.com/auth/calendar"]


def test_authorize_missing_configuration(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing credentials fail cleanly, listing only variable names."""
    client, _ = api
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(name, raising=False)

    response = client.get(AUTHORIZE_PATH)

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "GOOGLE_CLIENT_ID" in detail
    assert "GOOGLE_CLIENT_SECRET" in detail
    assert "GOOGLE_REDIRECT_URI" in detail
    # No secret value ever appears in the failure response.
    assert CLIENT_SECRET not in response.text


# ----------------------------------------------------------------------
# Callback
# ----------------------------------------------------------------------


def test_callback_missing_parameters(api) -> None:
    """Callback without code/state is a 400."""
    client, _ = api
    response = client.get(CALLBACK_PATH)
    assert response.status_code == 400
    assert "code" in response.json()["detail"]


def test_callback_rejects_google_error(api) -> None:
    """Google's own error redirect (e.g. access_denied) is a 400."""
    client, _ = api
    response = client.get(CALLBACK_PATH, params={"error": "access_denied"})
    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]


def test_callback_rejects_invalid_state(api) -> None:
    """A forged/unknown state never completes the flow."""
    client, _ = api
    response = client.get(
        CALLBACK_PATH, params={"code": AUTH_CODE, "state": "forged-state"}
    )
    assert response.status_code == 400
    assert "invalid or expired state" in response.json()["detail"]


def test_callback_success_stores_and_activates_token(api, monkeypatch) -> None:
    """A valid code exchange persists the refresh token and activates it."""
    client, factory = api
    opener = _TokenOpener(
        body=json.dumps(
            {
                "access_token": "access-test",
                "expires_in": 3599,
                "refresh_token": REFRESH_TOKEN,
                "scope": " ".join(DEFAULT_SCOPES),
            }
        ).encode()
    )
    state = _grant(client, opener, monkeypatch)

    response = client.get(
        CALLBACK_PATH, params={"code": AUTH_CODE, "state": state}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["provider"] == "google"
    assert body["configured"] is True
    assert set(body["scopes"]) == set(DEFAULT_SCOPES)
    # No token or secret leaks into the response.
    assert REFRESH_TOKEN not in response.text
    assert CLIENT_SECRET not in response.text
    assert "access-test" not in response.text

    # The refresh token is persisted in the dedicated credential table.
    with factory() as db:
        row = GoogleOAuthRepository(db).get("google")
        assert row is not None
        assert row.refresh_token == REFRESH_TOKEN
        assert set(row.scopes) == set(DEFAULT_SCOPES)

    # And activated in the process environment for the connectors.
    assert os.environ.get("GOOGLE_REFRESH_TOKEN") == REFRESH_TOKEN


def test_callback_exchange_auth_failure(api, monkeypatch) -> None:
    """Google rejecting the code maps to 502 and leaks nothing."""
    client, factory = api
    opener = _TokenOpener(body=b'{"error":"invalid_grant"}', status=401)
    state = _grant(client, opener, monkeypatch)

    response = client.get(CALLBACK_PATH, params={"code": AUTH_CODE, "state": state})

    assert response.status_code == 502
    assert "AUTHENTICATION_FAILED" in response.json()["detail"]
    assert CLIENT_SECRET not in response.text
    assert AUTH_CODE not in response.text
    # Nothing was persisted or activated.
    with factory() as db:
        assert GoogleOAuthRepository(db).get("google") is None
    assert os.environ.get("GOOGLE_REFRESH_TOKEN") is None


def test_callback_exchange_rate_limited(api, monkeypatch) -> None:
    """A rate-limited token endpoint maps to HTTP 429."""
    client, _ = api
    opener = _TokenOpener(body=b'{"error":"rate_limit_exceeded"}', status=429)
    state = _grant(client, opener, monkeypatch)

    response = client.get(CALLBACK_PATH, params={"code": AUTH_CODE, "state": state})

    assert response.status_code == 429
    assert "RATE_LIMITED" in response.json()["detail"]


# ----------------------------------------------------------------------
# Environment hydration
# ----------------------------------------------------------------------


def test_load_into_environment_hydrates_stored_token(api) -> None:
    """Startup hydration re-activates a stored refresh token."""
    _, factory = api
    with factory() as db:
        GoogleOAuthRepository(db).upsert("google", REFRESH_TOKEN, list(DEFAULT_SCOPES))

    os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
    with factory() as db:
        loaded = GoogleOAuthService(db).load_into_environment()

    assert loaded is True
    assert os.environ.get("GOOGLE_REFRESH_TOKEN") == REFRESH_TOKEN
    os.environ.pop("GOOGLE_REFRESH_TOKEN", None)


def test_load_into_environment_noop_without_token(api) -> None:
    """No stored token means no environment change and no error."""
    _, factory = api
    os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
    with factory() as db:
        loaded = GoogleOAuthService(db).load_into_environment()
    assert loaded is False
    assert os.environ.get("GOOGLE_REFRESH_TOKEN") is None
