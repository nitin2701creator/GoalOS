"""End-to-end route tests for the Integrations Manager OAuth flows.

Covers: connect persisting mandatory OAuth state, callback state
validation (missing / invalid / mismatched / replayed), the full Twitter
PKCE flow, token refresh via the API, auto-refresh on expired tokens in
``test_connection``, and the canonical status vocabulary. All token
endpoints are hermetic via a fake opener.
"""
from __future__ import annotations

import datetime as _dt
import io
import json
import os
import secrets
from urllib.error import HTTPError

os.environ.setdefault("IM_ENCRYPTION_KEY", secrets.token_hex(32))
_IM_TEST_DB = os.environ.get("IM_DATABASE_URL", "sqlite:///:memory:").replace("sqlite:///", "")
os.environ.setdefault("IM_ADMIN_USERNAME", "testadmin")
os.environ.setdefault("IM_ADMIN_PASSWORD", "testpass123")
os.environ.setdefault("IM_JWT_SECRET", "im-test-jwt-secret")
os.environ.setdefault("TWITTER_CLIENT_ID", "tw-test-client-id")
os.environ.setdefault("TWITTER_CLIENT_SECRET", "tw-test-client-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "ga-test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "ga-test-client-secret")
os.environ.setdefault("LINKEDIN_CLIENT_ID", "li-test-client-id")
os.environ.setdefault("LINKEDIN_CLIENT_SECRET", "li-test-client-secret")
os.environ.setdefault("REDDIT_CLIENT_ID", "rd-test-client-id")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "rd-test-client-secret")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from integrations_manager.app.main import app  # noqa: E402
from integrations_manager.app.models import (  # noqa: E402
    ConnectionStatus,
    Integration,
    OAuthState,
    OAuthToken,
)
from integrations_manager.app.providers.base import TestResult  # noqa: E402


class RouteOpener:
    """Serves token responses and records requests; 4xx raises HTTPError."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.overrides: dict[str, tuple[int, dict]] = {}

    def set_url(self, url: str, status: int, payload: dict) -> None:
        self.overrides[url] = (status, payload)

    def __call__(self, request, timeout=None):  # noqa: ANN001
        from tests.integration_helpers import FakeResponse

        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        body = getattr(request, "data", None)
        headers = {
            key.lower(): value
            for key, value in (request.header_items() if hasattr(request, "header_items") else [])
        }
        self.calls.append({
            "method": method,
            "url": url,
            "body": body.decode() if isinstance(body, bytes) else (body or ""),
            "headers": headers,
        })
        default = {
            "access_token": "route_fresh_" + url.split("/")[-1][:8],
            "refresh_token": "route_fresh_refresh",
            "expires_in": 7200,
            "token_type": "Bearer",
            "scope": "",
        }
        status, payload = self.overrides.get(url, (200, default))
        data = json.dumps(payload).encode()
        if status >= 400:
            raise HTTPError(
                url, status, "opener error",
                {"Content-Type": "application/json"}, io.BytesIO(data),
            )
        return FakeResponse(data, url, status=status, content_type="application/json")


@pytest.fixture(autouse=True)
def _fresh_db_file():
    if os.path.exists(_IM_TEST_DB):
        os.remove(_IM_TEST_DB)
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def opener(monkeypatch):
    opener = RouteOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    return opener


@pytest.fixture
def auth_headers(client):
    resp = client.post("/api/auth/login", json={
        "username": "testadmin",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    return {
        "Authorization": f"Bearer {data['access_token']}",
        "X-CSRF-Token": data["csrf_token"],
    }


def _with_fresh_csrf(client, auth_headers) -> dict:
    csrf = client.get("/api/auth/csrf", headers=auth_headers).json()["csrf_token"]
    return {**auth_headers, "X-CSRF-Token": csrf}


def _db():
    return app.state.db


def _enc():
    return app.state.encryption


def _integration(slug: str) -> Integration:
    return _db().query(Integration).filter(Integration.slug == slug).first()


def _add_token(slug, *, expires_at, refresh_token: str | None):
    enc = _enc()
    integ = _integration(slug)
    row = OAuthToken(
        integration_id=integ.id,
        provider=slug,
        encrypted_access_token=enc.encrypt("stale_access"),
        encrypted_refresh_token=enc.encrypt(refresh_token) if refresh_token else None,
        expires_at=expires_at,
    )
    _db().add(row)
    _db().commit()
    return row


class TestConnect:
    def test_connect_twitter_persists_state_with_pkce(self, client, auth_headers):
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/twitter/connect", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        params = dict(p.split("=", 1) for p in data["redirect_url"].split("?", 1)[1].split("&"))
        assert params["client_id"] == "tw-test-client-id"
        assert params["code_challenge_method"] == "S256"
        assert "code_challenge" in params
        assert "state" in params
        assert "code_verifier" not in params

        row = _db().query(OAuthState).filter(OAuthState.state == params["state"]).first()
        assert row is not None
        assert row.provider == "twitter"
        assert row.consumed_at is None
        # The PANDA verifier is encrypted at rest and survives to the callback.
        verifier = _enc().decrypt(row.encrypted_code_verifier)
        assert len(verifier) >= 43

    def test_connect_unconfigured_oauth_client_400(self, client, auth_headers, monkeypatch):
        # Simulate a provider that has no OAuth client credentials configured;
        # the connect route must fail fast with "not configured".
        monkeypatch.setattr(
            "integrations_manager.app.oauth_flow._client_credentials",
            lambda slug: ("", ""),
        )
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/meta/connect", headers=h)
        assert res.status_code == 400
        assert "not configured" in res.json()["detail"]


class TestCallbackValidation:
    def test_missing_state_rejected(self, client):
        res = client.get("/api/oauth/twitter/callback", params={"code": "x"})
        assert res.status_code == 400
        assert "state" in res.json()["detail"].lower()

    def test_unknown_state_rejected(self, client):
        res = client.get("/api/oauth/twitter/callback", params={
            "code": "x", "state": "not-a-real-state",
        })
        assert res.status_code == 400

    def test_expired_state_rejected(self, client, auth_headers):
        h = _with_fresh_csrf(client, auth_headers)
        client.post("/api/integrations/google_analytics/connect", headers=h)
        row = _db().query(OAuthState).first()
        row.expires_at = _dt.datetime.utcnow() - _dt.timedelta(seconds=1)
        _db().commit()
        res = client.get("/api/oauth/google_analytics/callback", params={
            "code": "x", "state": row.state,
        })
        assert res.status_code == 400

    def test_state_mismatch_rejected(self, client, auth_headers):
        h = _with_fresh_csrf(client, auth_headers)
        client.post("/api/integrations/google_analytics/connect", headers=h)
        ga_state = _db().query(OAuthState).first().state
        res = client.get("/api/oauth/twitter/callback", params={
            "code": "x", "state": ga_state,
        })
        assert res.status_code == 400
        assert "mismatch" in res.json()["detail"].lower()


class TestTwitterFlow:
    def test_full_pkce_flow(self, client, auth_headers, opener):
        h = _with_fresh_csrf(client, auth_headers)
        connect = client.post("/api/integrations/twitter/connect", headers=h).json()
        params = dict(p.split("=", 1) for p in connect["redirect_url"].split("?", 1)[1].split("&"))
        state = params["state"]
        row = _db().query(OAuthState).filter(OAuthState.state == state).first()
        verifier = _enc().decrypt(row.encrypted_code_verifier)

        res = client.get("/api/oauth/twitter/callback", params={"code": "auth-code", "state": state})
        assert res.status_code == 200
        assert "Connected" in res.text

        # The token exchange must send the persisted PKCE verifier + client id.
        call = opener.calls[0]
        assert call["url"] == "https://api.twitter.com/2/oauth2/token"
        body = dict(q.split("=", 1) for q in call["body"].split("&"))
        assert body["code_verifier"] == verifier
        assert body["client_id"] == "tw-test-client-id"

        # Tokens are encrypted at rest; the access token is a real value.
        oauth = _db().query(OAuthToken).filter(
            OAuthToken.integration_id == _integration("twitter").id
        ).first()
        assert oauth is not None
        assert _enc().decrypt(oauth.encrypted_access_token).startswith("route_fresh_")
        assert _enc().decrypt(oauth.encrypted_refresh_token) == "route_fresh_refresh"
        assert oauth.expires_at > _dt.datetime.utcnow()

        status = _db().query(ConnectionStatus).filter(
            ConnectionStatus.integration_id == _integration("twitter").id
        ).first()
        assert status.status == "connected"

        status_res = client.get("/api/integrations/twitter/status", headers=auth_headers)
        assert status_res.json()["status"] == "connected"

        # State is one-time use.
        replay = client.get("/api/oauth/twitter/callback", params={
            "code": "auth-code", "state": state,
        })
        assert replay.status_code == 400

    def test_callback_error_query_param_rejected(self, client, auth_headers):
        h = _with_fresh_csrf(client, auth_headers)
        state = dict(p.split("=", 1) for p in client.post(
            "/api/integrations/twitter/connect", headers=h
        ).json()["redirect_url"].split("?", 1)[1].split("&"))["state"]
        res = client.get("/api/oauth/twitter/callback", params={
            "code": "x", "state": state, "error": "access_denied",
        })
        assert res.status_code == 400


class TestGoogleFlow:
    def test_non_pkce_exchange_succeeds(self, client, auth_headers, opener):
        h = _with_fresh_csrf(client, auth_headers)
        connect = client.post("/api/integrations/google_analytics/connect", headers=h).json()
        params = dict(p.split("=", 1) for p in connect["redirect_url"].split("?", 1)[1].split("&"))
        res = client.get("/api/oauth/google_analytics/callback", params={
            "code": "ga-code", "state": params["state"],
        })
        assert res.status_code == 200
        call = opener.calls[0]
        assert call["url"] == "https://oauth2.googleapis.com/token"
        body = dict(q.split("=", 1) for q in call["body"].split("&"))
        assert body["grant_type"] == "authorization_code"
        assert body["client_id"] == "ga-test-client-id"


class TestRefresh:
    def test_refresh_endpoint_updates_token_and_status(self, client, auth_headers, opener):
        _add_token("linkedin", expires_at=_dt.datetime.utcnow() - _dt.timedelta(hours=1),
                   refresh_token="stored_refresh")
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/oauth/linkedin/refresh", headers=h)
        assert res.status_code == 200
        assert res.json()["success"] is True

        oauth = _db().query(OAuthToken).filter(
            OAuthToken.integration_id == _integration("linkedin").id
        ).first()
        assert _enc().decrypt(oauth.encrypted_access_token).startswith("route_fresh_")
        assert oauth.expires_at > _dt.datetime.utcnow()

        status = _db().query(ConnectionStatus).filter(
            ConnectionStatus.integration_id == _integration("linkedin").id
        ).first()
        assert status.status == "connected"

    def test_refresh_requires_refresh_token(self, client, auth_headers, opener):
        _add_token("linkedin", expires_at=_dt.datetime.utcnow() - _dt.timedelta(hours=1),
                   refresh_token=None)
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/oauth/linkedin/refresh", headers=h)
        assert res.status_code == 409

    def test_refresh_failure_marks_expired(self, client, auth_headers, opener):
        _add_token("reddit", expires_at=_dt.datetime.utcnow() - _dt.timedelta(hours=1),
                   refresh_token="expired_refresh")
        opener.set_url(
            "https://www.reddit.com/api/v1/access_token",
            status=400,
            payload={"error": "invalid_grant"},
        )
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/oauth/reddit/refresh", headers=h)
        assert res.status_code == 400
        status = _db().query(ConnectionStatus).filter(
            ConnectionStatus.integration_id == _integration("reddit").id
        ).first()
        assert status.status == "expired"


class TestAutoRefresh:
    class FakeProvider:
        def __init__(self):
            self.credentials = None

        async def test_connection(self, credentials):
            self.credentials = credentials
            return TestResult(success=True, message="tested-ok", status="connected")

    def test_expired_token_auto_refreshes_before_test(self, client, auth_headers, opener, monkeypatch):
        _add_token("google_analytics", expires_at=_dt.datetime.utcnow() - _dt.timedelta(seconds=1),
                   refresh_token="stored_refresh")
        fake = self.FakeProvider()
        monkeypatch.setattr(
            "integrations_manager.app.routers.integrations._get_provider",
            lambda slug: fake,
        )
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/google_analytics/test", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["status"] == "connected"
        # Refresh endpoint was hit with the stored refresh token.
        refresh_calls = [c for c in opener.calls if c["url"] == "https://oauth2.googleapis.com/token"]
        assert refresh_calls
        body = dict(q.split("=", 1) for q in refresh_calls[0]["body"].split("&"))
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "stored_refresh"
        # Provider saw the fresh access token, not the stale one.
        assert fake.credentials["access_token"].startswith("route_fresh_")

    def test_expired_token_without_refresh_is_never_silently_healthy(self, client, auth_headers, opener, monkeypatch):
        _add_token("meta", expires_at=_dt.datetime.utcnow() - _dt.timedelta(seconds=1),
                   refresh_token=None)
        monkeypatch.setattr(
            "integrations_manager.app.routers.integrations._get_provider",
            lambda slug: self.FakeProvider(),
        )
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/meta/test", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False
        assert data["status"] == "expired"
        assert "expired" in data["message"].lower()
        assert opener.calls == []  # provider must never be called

    def test_expired_token_refresh_failure_marks_expired(self, client, auth_headers, opener, monkeypatch):
        _add_token("reddit", expires_at=_dt.datetime.utcnow() - _dt.timedelta(seconds=1),
                   refresh_token="stale_refresh")
        opener.set_url(
            "https://www.reddit.com/api/v1/access_token",
            status=400,
            payload={"error": "invalid_grant", "error_description": "refresh denied"},
        )
        monkeypatch.setattr(
            "integrations_manager.app.routers.integrations._get_provider",
            lambda slug: self.FakeProvider(),
        )
        h = _with_fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/reddit/test", headers=h)
        data = res.json()
        assert data["success"] is False
        assert data["status"] == "expired"
        status = _db().query(ConnectionStatus).filter(
            ConnectionStatus.integration_id == _integration("reddit").id
        ).first()
        assert status.status == "expired"


class TestStatusVocabulary:
    def test_oauth_without_token_is_auth_required(self, client, auth_headers):
        res = client.get("/api/integrations/twitter/status", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["status"] == "auth_required"

    def test_expired_token_reflected_in_status(self, client, auth_headers):
        _add_token("linkedin", expires_at=_dt.datetime.utcnow() - _dt.timedelta(seconds=1),
                   refresh_token="r")
        res = client.get("/api/integrations/linkedin/status", headers=auth_headers)
        assert res.json()["status"] == "expired"

    def test_disabled_integration_reports_disabled(self, client, auth_headers):
        integ = _integration("twitter")
        integ.is_enabled = False
        _db().commit()
        res = client.get("/api/integrations/twitter/status", headers=auth_headers)
        assert res.json()["status"] == "disabled"
        assert res.json()["is_enabled"] is False

        listing = client.get("/api/integrations", headers=auth_headers).json()
        twitter = next(i for i in listing if i["slug"] == "twitter")
        assert twitter["status"] == "disabled"
        assert twitter["is_enabled"] is False