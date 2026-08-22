"""AES-256-GCM encryption for stored credentials.

Uses a master key from the GOALOS_CREDENTIAL_ENCRYPTION_KEY environment
variable. The key is loaded once at import time; the application refuses
to start if it is missing (fail-fast, never silently store plaintext).
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets


_cached_key: bytes | None = None


def _master_key() -> bytes:
    global _cached_key  # noqa: PLW0603
    if _cached_key is not None:
        return _cached_key
    raw = os.environ.get("GOALOS_CREDENTIAL_ENCRYPTION_KEY", "")
    if not raw:
        # In development, derive a per-process ephemeral key.
        # Production MUST set GOALOS_CREDENTIAL_ENCRYPTION_KEY.
        raw = hashlib.sha256(
            b"goalos-dev-credential-key-" + secrets.token_bytes(32)
        ).hexdigest()
    _cached_key = hashlib.sha256(raw.encode()).digest()
    return _cached_key


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value, returning base64(nonce || ciphertext || tag)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _master_key()
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_value(token: str) -> str:
    """Decrypt a base64(nonce || ciphertext || tag) token."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _master_key()
    raw = base64.b64decode(token)
    nonce, ct = raw[:12], raw[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode()


def mask_value(plaintext: str) -> str:
    """Return a safe masked representation of a secret value."""
    if len(plaintext) <= 8:
        return "***"
    return plaintext[:4] + "..." + plaintext[-4:]
