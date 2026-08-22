"""Tests for credential encryption/decryption."""
import os
import pytest
import secrets

# Set encryption key before importing
os.environ["IM_ENCRYPTION_KEY"] = secrets.token_hex(32)
os.environ["IM_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["IM_ADMIN_PASSWORD"] = "test-password"

from integrations_manager.app.encryption import CredentialEncryption


class TestCredentialEncryption:
    """Test AES-256-GCM encryption layer."""

    def test_encrypt_decrypt_roundtrip(self):
        enc = CredentialEncryption()
        plaintext = "my-secret-api-key-12345"
        ciphertext = enc.encrypt(plaintext)
        assert ciphertext != plaintext
        decrypted = enc.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_different_ciphertext_each_time(self):
        enc = CredentialEncryption()
        plaintext = "same-value"
        ct1 = enc.encrypt(plaintext)
        ct2 = enc.encrypt(plaintext)
        # Nonce is random, so ciphertexts differ
        assert ct1 != ct2
        # But both decrypt to the same value
        assert enc.decrypt(ct1) == plaintext
        assert enc.decrypt(ct2) == plaintext

    def test_encrypt_empty_string(self):
        enc = CredentialEncryption()
        ct = enc.encrypt("")
        assert enc.decrypt(ct) == ""

    def test_encrypt_unicode(self):
        enc = CredentialEncryption()
        plaintext = "Ünïcödé🔑secret"
        ct = enc.encrypt(plaintext)
        assert enc.decrypt(ct) == plaintext

    def test_decrypt_wrong_ciphertext_raises(self):
        enc = CredentialEncryption()
        with pytest.raises(Exception):
            enc.decrypt("invalid-base64-or-garbage")

    def test_missing_key_raises(self):
        old = os.environ.pop("IM_ENCRYPTION_KEY", None)
        try:
            with pytest.raises(ValueError, match="IM_ENCRYPTION_KEY"):
                CredentialEncryption()
        finally:
            if old:
                os.environ["IM_ENCRYPTION_KEY"] = old

    def test_wrong_key_length_raises(self):
        old = os.environ.get("IM_ENCRYPTION_KEY")
        os.environ["IM_ENCRYPTION_KEY"] = "abcd"  # Too short
        try:
            with pytest.raises(ValueError, match="32-byte"):
                CredentialEncryption()
        finally:
            if old:
                os.environ["IM_ENCRYPTION_KEY"] = old

    def test_generate_key_format(self):
        key = CredentialEncryption.generate_key()
        assert len(key) == 64  # 32 bytes = 64 hex chars
        int(key, 16)  # Must be valid hex

    def test_long_secret(self):
        enc = CredentialEncryption()
        plaintext = "x" * 10000
        ct = enc.encrypt(plaintext)
        assert enc.decrypt(ct) == plaintext
