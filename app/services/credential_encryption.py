"""AES-256-GCM encryption for stored credentials.

Uses a master key from the GOALOS_CREDENTIAL_ENCRYPTION_KEY environment
variable. The key is resolved lazily and the application fails fast the
first time it is needed if the key is missing — a credential can never be
silently stored under an un-recoverable key. Development and tests can
opt into a per-process ephemeral key by setting
GOALOS_CREDENTIAL_EPHEMERAL_KEY=1.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets


_cached_key: bytes | None = None

_ALLOW_EPHEMERAL_KEY = os.getenv("GOALOS_CREDENTIAL_EPHEMERAL_KEY", "0").lower() in (
    "1", "true", "yes",
)


def _master_key() -> bytes:
    global _cached_key  # noqa: PLW0603
    if _cached_key is not None:
        return _cached_key
    raw = os.environ.get("GOALOS_CREDENTIAL_ENCRYPTION_KEY", "")
    if not raw:
        if not _ALLOW_EPHEMERAL_KEY:
            raise RuntimeError(
                "GOALOS_CREDENTIAL_ENCRYPTION_KEY is not set. Set a 64-char hex "
                "key, e.g. `python -c 'import secrets; print(secrets.token_hex(32))'`, "
                "or opt into the dev-only ephemeral key with "
                "GOALOS_CREDENTIAL_EPHEMERAL_KEY=1."
            )
        # Development/tests only: per-process ephemeral key, never persisted.
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
