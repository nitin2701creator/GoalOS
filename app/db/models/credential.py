"""Encrypted credential storage for integrations.

Stores encrypted API keys, secrets, tokens, and other sensitive values
that configure GoalOS integrations. Every secret is encrypted at rest
using AES-256-GCM with a master key from the environment. Secrets are
never returned in plaintext through any API endpoint.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EncryptedCredential(Base):
    """A stored credential for an integration."""

    __tablename__ = "encrypted_credentials"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: Integration slug (e.g. "woocommerce", "google_analytics").
    integration: Mapped[str] = mapped_column(
        String(120), index=True, nullable=False
    )
    #: Field key (e.g. "consumer_key", "api_key", "access_token").
    field_key: Mapped[str] = mapped_column(String(120), nullable=False)
    #: Encrypted value (base64-encoded AES-256-GCM ciphertext).
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    #: Non-sensitive display hint (e.g. "sk-...xyz" for an API key).
    display_hint: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    #: When this credential was last set.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
