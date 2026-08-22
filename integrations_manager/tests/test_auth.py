"""Tests for admin authentication, JWT, and CSRF protection."""
import os
import secrets
import pytest

os.environ["IM_ENCRYPTION_KEY"] = secrets.token_hex(32)
os.environ["IM_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["IM_ADMIN_USERNAME"] = "testadmin"
os.environ["IM_ADMIN_PASSWORD"] = "testpass123"

from integrations_manager.app.auth import (
    create_access_token,
    create_csrf_token,
    decode_access_token,
    validate_csrf_token,
    _hash_password,
)


class TestPasswordHashing:
    def test_hash_deterministic(self):
        h1 = _hash_password("secret")
        h2 = _hash_password("secret")
        assert h1 == h2

    def test_different_passwords_different_hashes(self):
        h1 = _hash_password("pass1")
        h2 = _hash_password("pass2")
        assert h1 != h2


class TestJWT:
    def test_create_and_decode_token(self):
        token = create_access_token("admin")
        payload = decode_access_token(token)
        assert payload["sub"] == "admin"
        assert "exp" in payload
        assert "jti" in payload

    def test_invalid_token_raises(self):
        with pytest.raises(Exception):
            decode_access_token("invalid.token.here")

    def test_different_tokens_different_jti(self):
        t1 = create_access_token("admin")
        t2 = create_access_token("admin")
        p1 = decode_access_token(t1)
        p2 = decode_access_token(t2)
        assert p1["jti"] != p2["jti"]


class TestCSRF:
    def test_create_and_validate_token(self):
        token = create_csrf_token()
        assert validate_csrf_token(token) is True

    def test_invalid_token_rejected(self):
        assert validate_csrf_token("invalid") is False

    def test_empty_token_rejected(self):
        assert validate_csrf_token(None) is False
        assert validate_csrf_token("") is False

    def test_token_single_use(self):
        token = create_csrf_token()
        assert validate_csrf_token(token) is True
        # Second use should fail (consumed)
        assert validate_csrf_token(token) is False
