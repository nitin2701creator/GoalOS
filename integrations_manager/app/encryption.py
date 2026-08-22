"""AES-256-GCM encryption for credential storage at rest.

Master key is loaded from IM_ENCRYPTION_KEY (hex-encoded 32-byte key).
Never log, print, or expose the key or plaintext values.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CredentialEncryption:
    """Encrypt/decrypt credential values using AES-256-GCM."""

    def __init__(self, key_hex: str | None = None) -> None:
        raw = key_hex or os.getenv("IM_ENCRYPTION_KEY", "")
        if not raw:
            raise ValueError(
                "IM_ENCRYPTION_KEY environment variable is required. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        key = bytes.fromhex(raw)
        if len(key) != 32:
            raise ValueError("IM_ENCRYPTION_KEY must be a 32-byte hex string (64 hex chars)")
        self._key = key

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext, return base64-encoded ciphertext with embedded nonce."""
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        aesgcm = AESGCM(self._key)
        ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # Store nonce + ciphertext together
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, ciphertext_b64: str) -> str:
        """Decrypt base64-encoded ciphertext back to plaintext."""
        raw = base64.b64decode(ciphertext_b64)
        nonce, ct = raw[:12], raw[12:]
        aesgcm = AESGCM(self._key)
        return aesgcm.decrypt(nonce, ct, None).decode("utf-8")

    @staticmethod
    def generate_key() -> str:
        """Generate a new random 32-byte hex key."""
        return secrets.token_hex(32)


import secrets  # noqa: E402 (needed for generate_key)
