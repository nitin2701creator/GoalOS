"""Tests for the Integrations Manager API endpoints."""
import os
import secrets

# Set env before any imports
os.environ["IM_ENCRYPTION_KEY"] = secrets.token_hex(32)
os.environ["IM_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["IM_ADMIN_USERNAME"] = "testadmin"
os.environ["IM_ADMIN_PASSWORD"] = "testpass123"
os.environ["IM_JWT_SECRET"] = "test-jwt-secret"

import pytest
from fastapi.testclient import TestClient

from integrations_manager.app.main import app


@pytest.fixture
def client():
    """Create a test client with fresh DB."""
    from integrations_manager.app.models import create_db_engine, init_db, get_session_factory, Integration
    from integrations_manager.app.providers import PROVIDER_REGISTRY

    engine = create_db_engine("sqlite:///:memory:")
    init_db(engine)
    SessionLocal = get_session_factory(engine)
    db = SessionLocal()

    # Seed integrations
    for slug, cls in PROVIDER_REGISTRY.items():
        info = cls().info()
        db.add(Integration(
            slug=info.slug, name=info.name, description=info.description,
            icon=info.icon, auth_type=info.auth_type, is_enabled=True,
        ))
    db.commit()

    # Override app state
    app.state.db = db
    app.state.engine = engine
    from integrations_manager.app.encryption import CredentialEncryption
    app.state.encryption = CredentialEncryption()
    app.state.oauth_states = {}

    with TestClient(app) as c:
        yield c

    db.close()


@pytest.fixture
def auth_headers(client):
    """Get auth headers with JWT + CSRF token."""
    login_res = client.post("/api/auth/login", json={
        "username": "testadmin",
        "password": "testpass123",
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    csrf = login_res.json()["csrf_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-CSRF-Token": csrf,
    }


class TestHealth:
    def test_health_returns_200(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestAuth:
    def test_login_success(self, client):
        res = client.post("/api/auth/login", json={
            "username": "testadmin",
            "password": "testpass123",
        })
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "csrf_token" in data

    def test_login_wrong_password(self, client):
        res = client.post("/api/auth/login", json={
            "username": "testadmin",
            "password": "wrongpassword",
        })
        assert res.status_code == 401

    def test_login_wrong_username(self, client):
        res = client.post("/api/auth/login", json={
            "username": "wronguser",
            "password": "testpass123",
        })
        assert res.status_code == 401

    def test_csrf_token_endpoint(self, client, auth_headers):
        res = client.get("/api/auth/csrf", headers=auth_headers)
        assert res.status_code == 200
        assert "csrf_token" in res.json()


class TestIntegrations:
    def test_list_integrations(self, client, auth_headers):
        res = client.get("/api/integrations", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        slugs = [i["slug"] for i in data]
        assert "woocommerce" in slugs
        assert "google_analytics" in slugs
        assert "meta" in slugs
        assert "linkedin" in slugs
        assert "twitter" in slugs
        assert "reddit" in slugs

    def test_list_requires_auth(self, client):
        res = client.get("/api/integrations")
        assert res.status_code in (401, 403)

    def test_get_integration_detail(self, client, auth_headers):
        res = client.get("/api/integrations/woocommerce", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["slug"] == "woocommerce"
        assert data["name"] == "WooCommerce"
        assert "credential_fields" in data
        assert len(data["credential_fields"]) > 0

    def test_get_integration_not_found(self, client, auth_headers):
        res = client.get("/api/integrations/nonexistent", headers=auth_headers)
        assert res.status_code == 404

    def test_get_status(self, client, auth_headers):
        res = client.get("/api/integrations/woocommerce/status", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "not_configured"


def _fresh_csrf(client, auth_headers):
    """Get a fresh CSRF token (tokens are single-use)."""
    csrf_res = client.get("/api/auth/csrf", headers=auth_headers)
    return {**auth_headers, "X-CSRF-Token": csrf_res.json()["csrf_token"]}


class TestCredentials:
    def test_save_credentials(self, client, auth_headers):
        h = _fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/woocommerce/credentials", headers=h, json={
            "credentials": {
                "store_url": "https://example.com",
                "consumer_key": "ck_test123",
                "consumer_secret": "cs_secret456",
            },
        })
        assert res.status_code == 200
        assert res.json()["success"] is True

    def test_get_masked_credentials(self, client, auth_headers):
        # Save first (fresh CSRF)
        h = _fresh_csrf(client, auth_headers)
        client.post("/api/integrations/woocommerce/credentials", headers=h, json={
            "credentials": {
                "store_url": "https://example.com",
                "consumer_key": "ck_test123",
                "consumer_secret": "cs_secret456",
            },
        })
        # Retrieve masked
        res = client.get("/api/integrations/woocommerce/credentials", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) > 0
        for cred in data:
            assert "key" in cred
            assert "masked_value" in cred
            # NEVER expose raw secrets
            assert "ck_test123" not in cred["masked_value"]
            assert "cs_secret456" not in cred["masked_value"]
            assert "https://example.com" not in cred["masked_value"]

    def test_credentials_never_in_api_response(self, client, auth_headers):
        # Save secret value (fresh CSRF)
        h = _fresh_csrf(client, auth_headers)
        client.post("/api/integrations/woocommerce/credentials", headers=h, json={
            "credentials": {"consumer_secret": "supersecretvalue"},
        })
        # GET integrations list should not contain secrets
        res = client.get("/api/integrations", headers=auth_headers)
        assert "supersecretvalue" not in res.text

        # GET detail should not contain secrets
        res = client.get("/api/integrations/woocommerce", headers=auth_headers)
        assert "supersecretvalue" not in res.text

    def test_disconnect_removes_credentials(self, client, auth_headers):
        # Save credentials first (fresh CSRF)
        h1 = _fresh_csrf(client, auth_headers)
        r1 = client.post("/api/integrations/woocommerce/credentials", headers=h1, json={
            "credentials": {"consumer_key": "test-key-value"},
        })
        assert r1.status_code == 200

        # Verify they exist
        res = client.get("/api/integrations/woocommerce/credentials", headers=auth_headers)
        key_cred = next((c for c in res.json() if c["key"] == "consumer_key"), None)
        assert key_cred is not None
        assert key_cred["is_set"] is True

        # Disconnect (fresh CSRF token)
        h2 = _fresh_csrf(client, auth_headers)
        r2 = client.post("/api/integrations/woocommerce/disconnect", headers=h2)
        assert r2.status_code == 200

        # Verify credentials are gone
        res = client.get("/api/integrations/woocommerce/credentials", headers=auth_headers)
        for cred in res.json():
            assert cred["is_set"] is False


class TestTestConnection:
    def test_test_woocommerce_no_creds(self, client, auth_headers):
        h = _fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/woocommerce/test", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False

    def test_test_ga4_no_token(self, client, auth_headers):
        h = _fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/google_analytics/test", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is False

    def test_connect_returns_redirect_for_oauth(self, client, auth_headers):
        h = _fresh_csrf(client, auth_headers)
        res = client.post("/api/integrations/google_analytics/connect", headers=h)
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert "redirect_url" in data


class TestAuditLogs:
    def test_audit_logs_after_operations(self, client, auth_headers):
        # Perform some operations with fresh CSRF tokens
        h1 = _fresh_csrf(client, auth_headers)
        r1 = client.post("/api/integrations/woocommerce/credentials", headers=h1, json={
            "credentials": {"consumer_key": "test"},
        })
        assert r1.status_code == 200

        h2 = _fresh_csrf(client, auth_headers)
        r2 = client.post("/api/integrations/woocommerce/test", headers=h2)
        assert r2.status_code == 200

        # Check audit logs
        res = client.get("/api/integrations/woocommerce/audit", headers=auth_headers)
        assert res.status_code == 200
        logs = res.json()
        assert len(logs) >= 2
        actions = [log["action"] for log in logs]
        assert "save_credentials" in actions
        assert "test_connection" in actions


class TestSecretsNeverExposed:
    """Comprehensive test that secrets never leak through any API response."""

    SENSITIVE_VALUES = ["my-secret-api-key", "password123", "bearer-token-xyz"]

    def test_no_secrets_in_any_endpoint(self, client, auth_headers):
        # Save sensitive values (fresh CSRF)
        h = _fresh_csrf(client, auth_headers)
        client.post("/api/integrations/woocommerce/credentials", headers=h, json={
            "credentials": {
                "consumer_key": "my-secret-api-key",
                "consumer_secret": "password123",
            },
        })

        # Test every GET endpoint
        endpoints = [
            "/health",
            "/api/integrations",
            "/api/integrations/woocommerce",
            "/api/integrations/woocommerce/credentials",
            "/api/integrations/woocommerce/status",
            "/api/integrations/woocommerce/audit",
        ]
        for endpoint in endpoints:
            res = client.get(endpoint, headers=auth_headers)
            for sensitive in self.SENSITIVE_VALUES:
                assert sensitive not in res.text, (
                    f"Secret '{sensitive}' leaked in GET {endpoint}"
                )
