"""Unit tests for the Integrations Manager OAuth flow module.

Covers RFC 7636 PKCE generation, persisted authorization-state building,
provider-specific code exchange and refresh requests, and token rotation.
All HTTP is hermetic via an injected fake opener.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("IM_ENCRYPTION_KEY", secrets.token_hex(32))
os.environ.setdefault("TWITTER_CLIENT_ID", "tw-test-client-id")
os.environ.setdefault("TWITTER_CLIENT_SECRET", "tw-test-client-secret")
os.environ.setdefault("GOOGLE_CLIENT_ID", "ga-test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "ga-test-client-secret")
os.environ.setdefault("META_APP_ID", "meta-test-app-id")
os.environ.setdefault("META_APP_SECRET", "meta-test-app-secret")
os.environ.setdefault("LINKEDIN_CLIENT_ID", "li-test-client-id")
os.environ.setdefault("LINKEDIN_CLIENT_SECRET", "li-test-client-secret")
os.environ.setdefault("REDDIT_CLIENT_ID", "rd-test-client-id")
os.environ.setdefault("REDDIT_CLIENT_SECRET", "rd-test-client-secret")

import pytest  # noqa: E402

from app.integrations.http_client import HttpClient  # noqa: E402

from integrations_manager.app.encryption import CredentialEncryption  # noqa: E402
from integrations_manager.app.models import (  # noqa: E402
    Base,
    OAuthState,
    create_db_engine,
    get_session_factory,
    init_db,
)
from integrations_manager.app.oauth_flow import (  # noqa: E402
    OAuthExchangeError,
    OAuthNotConfiguredError,
    PKCE_PROVIDERS,
    REFRESHABLE_PROVIDERS,
    apply_refreshed_tokens,
    build_authorization_url,
    exchange_code,
    generate_pkce_pair,
    refresh_access_token,
    require_client_id,
    supports_refresh,
)
from integrations_manager.app.providers.base import OAuthConfig  # noqa: E402

from tests.integration_helpers import FakeResponse  # noqa: E402


def _sha256_b64url(value: str) -> str:
    return base64.urlsafe_b64encode(
        hashlib.sha256(value.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


class TokenOpener:
    """Serves canned token responses and records every request.

    Like ``urllib.request.urlopen``, non-2xx statuses raise ``HTTPError``
    so the client's real error handling path executes.
    """

    _VALID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")  # noqa: E501

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.default = {
            "access_token": "fresh_access_123",
            "refresh_token": "fresh_refresh_456",
            "expires_in": 7200,
            "token_type": "Bearer",
            "scope": "",
        }
        self.overrides: dict[str, tuple[int, dict]] = {}

    def set_url(self, url: str, status: int, payload: dict) -> None:
        self.overrides[url] = (status, payload)

    def __call__(self, request, timeout=None):  # noqa: ANN001
        import io
        from urllib.error import HTTPError

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
        status, payload = self.overrides.get(url, (200, self.default))
        data = json.dumps(payload).encode()
        if status >= 400:
            raise HTTPError(
                url, status,
                "opener error",
                {"Content-Type": "application/json"},
                io.BytesIO(data),
            )
        return FakeResponse(data, url, status=status, content_type="application/json")


@pytest.fixture
def db():
    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    Session = get_session_factory(engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def encryption():
    return CredentialEncryption()


class TestPKCE:
    def test_verifier_within_spec_charset_and_length(self):
        verifier, challenge = generate_pkce_pair()
        assert 43 <= len(verifier) <= 128
        assert set(verifier) <= TokenOpener._VALID_CHARS
        assert challenge == _sha256_b64url(verifier)

    def test_pairs_are_unique(self):
        a = generate_pkce_pair()
        b = generate_pkce_pair()
        assert a[0] != b[0]
        assert a[1] != b[1]

    def test_twitter_is_registered_for_pkce(self):
        assert "twitter" in PKCE_PROVIDERS


class TestClientCredentials:
    def test_twitter_client_id_resolves_from_settings(self):
        assert require_client_id("twitter") == "tw-test-client-id"

    def test_missing_client_id_fails_fast(self):
        with pytest.raises(OAuthNotConfiguredError):
            require_client_id("no_such_provider")


class TestBuildAuthorizationUrl:
    def test_twitter_uses_pkce_and_persists_state(self, db, encryption):
        url = build_authorization_url(
            slug="twitter",
            auth_url="https://twitter.com/i/oauth2/authorize",
            redirect_uri="http://localhost:8001/api/oauth/twitter/callback",
            scopes=["tweet.read", "tweet.write", "offline.access"],
            db=db,
            encryption=encryption,
        )
        parsed = urlsplit(url)
        params = parse_qs(parsed.query)

        assert params["client_id"] == ["tw-test-client-id"]
        assert params["response_type"] == ["code"]
        assert params["code_challenge_method"] == ["S256"]
        assert "code_verifier" not in params
        state = params["state"][0]
        assert len(state) >= 32

        row = db.query(OAuthState).filter(OAuthState.state == state).first()
        assert row is not None
        assert row.provider == "twitter"
        assert row.redirect_uri == "http://localhost:8001/api/oauth/twitter/callback"
        assert row.consumed_at is None
        verifier = encryption.decrypt(row.encrypted_code_verifier)
        # The challenge embedded in the URL must be derived from the verifier
        # we persisted (proves the callback can complete the exchange).
        assert params["code_challenge"][0] == _sha256_b64url(verifier)

    def test_reddit_keeps_permanent_duration(self, db, encryption):
        url = build_authorization_url(
            slug="reddit",
            auth_url="https://www.reddit.com/api/v1/authorize",
            redirect_uri="http://localhost:8001/api/oauth/reddit/callback",
            scopes=["identity"],
            db=db,
            encryption=encryption,
            extra_params={"duration": "permanent"},
        )
        params = parse_qs(urlsplit(url).query)
        assert params["duration"] == ["permanent"]
        assert "code_challenge" not in params

    def test_missing_client_id_fails_before_persisting(self, db, encryption):
        with pytest.raises(OAuthNotConfiguredError):
            build_authorization_url(
                slug="unknown_provider",
                auth_url="https://e.test/auth",
                redirect_uri="http://example.com/cb",
                scopes=["x"],
                db=db,
                encryption=encryption,
            )
        assert db.query(OAuthState).count() == 0


class TestExchangeCode:
    def test_twitter_requires_pkce_verifier(self, encryption):
        with pytest.raises(OAuthExchangeError, match="code_verifier"):
            exchange_code("twitter", "code", "http://example.com/cb", None)

    def test_twitter_sends_pkce_client_id_and_basic_auth(self):
        opener = TokenOpener()
        verifier, _ = generate_pkce_pair()
        result = exchange_code(
            "twitter",
            "auth_code_xyz",
            "http://localhost:8001/api/oauth/twitter/callback",
            verifier,
            client=HttpClient(opener=opener),
        )
        assert result["access_token"] == "fresh_access_123"
        call = opener.calls[0]
        assert call["method"] == "POST"
        assert call["url"] == "https://api.twitter.com/2/oauth2/token"
        body = parse_qs(call["body"])
        assert body["code_verifier"] == [verifier]
        assert body["client_id"] == ["tw-test-client-id"]
        assert body["redirect_uri"] == ["http://localhost:8001/api/oauth/twitter/callback"]
        assert body["grant_type"] == ["authorization_code"]
        auth = call["headers"].get("authorization", "")
        expected = "Basic " + base64.b64encode(
            b"tw-test-client-id:tw-test-client-secret"
        ).decode()
        assert auth == expected

    def test_google_analytics_sends_client_secret_in_body(self):
        opener = TokenOpener()
        exchange_code(
            "google_analytics",
            "code_ga",
            "http://localhost:8001/api/oauth/google_analytics/callback",
            client=HttpClient(opener=opener),
        )
        call = opener.calls[0]
        body = parse_qs(call["body"])
        assert body["client_id"] == ["ga-test-client-id"]
        assert body["client_secret"] == ["ga-test-client-secret"]
        assert body["redirect_uri"] == ["http://localhost:8001/api/oauth/google_analytics/callback"]

    def test_meta_uses_get_with_query_params(self):
        opener = TokenOpener()
        exchange_code(
            "meta",
            "code_meta",
            "http://localhost:8001/api/oauth/meta/callback",
            client=HttpClient(opener=opener),
        )
        call = opener.calls[0]
        assert call["method"] == "GET"
        parsed = urlsplit(call["url"])
        assert parsed.path == "/v19.0/oauth/access_token"
        params = parse_qs(parsed.query)
        assert params["client_id"] == ["meta-test-app-id"]
        assert params["code"] == ["code_meta"]

    def test_linkedin_uses_basic_auth(self):
        opener = TokenOpener()
        exchange_code(
            "linkedin",
            "code_li",
            "http://localhost:8001/api/oauth/linkedin/callback",
            client=HttpClient(opener=opener),
        )
        call = opener.calls[0]
        auth = call["headers"].get("authorization", "")
        expected = "Basic " + base64.b64encode(
            b"li-test-client-id:li-test-client-secret"
        ).decode()
        assert auth == expected

    def test_reddit_sets_user_agent(self):
        opener = TokenOpener()
        exchange_code(
            "reddit",
            "code_rd",
            "http://localhost:8001/api/oauth/reddit/callback",
            client=HttpClient(opener=opener),
        )
        call = opener.calls[0]
        assert "user-agent" in call["headers"]

    def test_rejects_token_endpoint_failure(self):
        opener = TokenOpener()
        opener.set_url(
            "https://api.twitter.com/2/oauth2/token",
            status=400,
            payload={"error": "invalid_grant", "error_description": "code expired"},
        )
        with pytest.raises(OAuthExchangeError, match="code expired"):
            exchange_code("twitter", "code", "http://example.com/cb", "v" * 48,
                          client=HttpClient(opener=opener))

    def test_unknown_provider_rejected(self):
        with pytest.raises(OAuthExchangeError):
            exchange_code("nope", "code", "http://example.com/cb", client=HttpClient(opener=TokenOpener()))


class TestRefresh:
    def test_meta_never_allows_refresh(self):
        assert "meta" not in REFRESHABLE_PROVIDERS
        assert not supports_refresh("meta")
        with pytest.raises(OAuthExchangeError, match="not supported"):
            refresh_access_token("meta", "rt", client=HttpClient(opener=TokenOpener()))

    def test_twitter_refresh_sends_client_id_and_basic_auth(self):
        opener = TokenOpener()
        result = refresh_access_token(
            "twitter",
            "stored_refresh",
            client=HttpClient(opener=opener),
        )
        assert result["access_token"] == "fresh_access_123"
        call = opener.calls[0]
        body = parse_qs(call["body"])
        assert body["grant_type"] == ["refresh_token"]
        assert body["refresh_token"] == ["stored_refresh"]
        assert body["client_id"] == ["tw-test-client-id"]
        assert call["headers"].get("authorization", "").startswith("Basic ")

    def test_google_refresh_sends_secret(self):
        opener = TokenOpener()
        refresh_access_token("google_analytics", "rt_ga", client=HttpClient(opener=opener))
        body = parse_qs(opener.calls[0]["body"])
        assert body["client_secret"] == ["ga-test-client-secret"]
        assert body["client_id"] == ["ga-test-client-id"]

    def test_reddit_refresh_sets_user_agent(self):
        opener = TokenOpener()
        refresh_access_token("reddit", "rt_rd", client=HttpClient(opener=opener))
        assert "user-agent" in opener.calls[0]["headers"]

    def test_linkedin_refresh_uses_basic_auth(self):
        opener = TokenOpener()
        refresh_access_token("linkedin", "rt_li", client=HttpClient(opener=opener))
        auth = opener.calls[0]["headers"].get("authorization", "")
        assert "Basic " in auth


class TestApplyRefreshedTokens:
    def test_rotates_tokens_and_expiry(self, db, encryption):
        from integrations_manager.app.models import Integration, OAuthToken
        import datetime as _dt

        integ = Integration(slug="twitter", name="X", auth_type="oauth2", is_enabled=True)
        db.add(integ)
        db.commit()

        token_row = OAuthToken(
            integration_id=integ.id,
            provider="twitter",
            encrypted_access_token=encryption.encrypt("old_access"),
            encrypted_refresh_token=encryption.encrypt("old_refresh"),
            expires_at=_dt.datetime.utcnow() - _dt.timedelta(seconds=10),
        )
        db.add(token_row)
        db.commit()

        access = apply_refreshed_tokens(token_row, encryption, {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": "3600",
            "scope": "tweet.read",
        })
        assert access == "new_access"
        assert encryption.decrypt(token_row.encrypted_access_token) == "new_access"
        assert encryption.decrypt(token_row.encrypted_refresh_token) == "new_refresh"
        assert token_row.expires_at > _dt.datetime.utcnow()

    def test_missing_access_token_raises(self, encryption):
        class _T:  # noqa: N801
            encrypted_access_token = ""
            encrypted_refresh_token = ""
            expires_at = None
            scopes = ""

        with pytest.raises(OAuthExchangeError, match="access_token"):
            apply_refreshed_tokens(_T(), encryption, {})


class TestOAuthConfigGetAuthUrlRegression:
    """Regression: client_id must not be derived from the redirect URI host."""

    def test_uses_configured_client_id(self):
        config = OAuthConfig(
            auth_url="https://twitter.com/i/oauth2/authorize",
            token_url="https://api.twitter.com/2/oauth2/token",
            scopes=["tweet.read"],
            redirect_uri="http://localhost:8001/api/oauth/twitter/callback",
            client_id="configured-client-123",
        )
        url = config.get_auth_url("state_abc", config.redirect_uri)
        assert "client_id=configured-client-123" in url
        assert "client_id=localhost" not in url
        assert "state=state_abc" in url