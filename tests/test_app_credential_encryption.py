"""Tests for app-side credential encryption fail-fast behavior (P0-1).

Verifies that without GOALOS_CREDENTIAL_ENCRYPTION_KEY the app refuses to
encrypt/decrypt (unless the explicit dev-only opt-in is set) and that a
configured key round-trips and never leaks via masking.
"""
from __future__ import annotations

import secrets

import pytest

import app.services.credential_encryption as module


@pytest.fixture
def reset_module(monkeypatch):
    monkeypatch.setattr(module, "_cached_key", None)
    yield


class TestFailFast:
    def test_missing_key_refuses_without_dev_optin(self, reset_module, monkeypatch):
        monkeypatch.delenv("GOALOS_CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr(module, "_ALLOW_EPHEMERAL_KEY", False)
        with pytest.raises(RuntimeError, match="GOALOS_CREDENTIAL_ENCRYPTION_KEY"):
            module.encrypt_value("supersecret")

    def test_decrypt_also_fails_fast(self, reset_module, monkeypatch):
        monkeypatch.delenv("GOALOS_CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr(module, "_ALLOW_EPHEMERAL_KEY", False)
        with pytest.raises(RuntimeError, match="GOALOS_CREDENTIAL_ENCRYPTION_KEY"):
            module.decrypt_value("AAAA")

    def test_dev_ephemeral_optin_roundtrips_in_process(self, reset_module, monkeypatch):
        monkeypatch.delenv("GOALOS_CREDENTIAL_ENCRYPTION_KEY", raising=False)
        monkeypatch.setattr(module, "_ALLOW_EPHEMERAL_KEY", True)
        token = module.encrypt_value("dev-secret")
        assert module.decrypt_value(token) == "dev-secret"

    def test_real_key_roundtrips(self, reset_module, monkeypatch):
        key = secrets.token_hex(32)
        monkeypatch.setenv("GOALOS_CREDENTIAL_ENCRYPTION_KEY", key)
        monkeypatch.setattr(module, "_ALLOW_EPHEMERAL_KEY", False)
        token = module.encrypt_value("persistent-secret")
        assert module.decrypt_value(token) == "persistent-secret"

    def test_encryption_is_nonce_randomized(self, reset_module, monkeypatch):
        key = secrets.token_hex(32)
        monkeypatch.setenv("GOALOS_CREDENTIAL_ENCRYPTION_KEY", key)
        token_a = module.encrypt_value("same-value")
        token_b = module.encrypt_value("same-value")
        assert token_a != token_b


class TestMasking:
    def test_mask_never_reveals_secret(self):
        secret = "super-secret-api-key-123"
        masked = module.mask_value(secret)
        assert secret not in masked
        assert "..." in masked

    def test_mask_short_values(self):
        assert module.mask_value("abc") == "***"

    def test_mask_empty(self):
        assert module.mask_value("") == "***"