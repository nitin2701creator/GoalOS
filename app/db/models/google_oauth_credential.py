"""
Google OAuth credential database model.

One row stores the refresh token granted through the GoalOS Google OAuth
web flow (``GET /api/v1/integrations/google/authorize`` →
``GET /api/v1/integrations/google/callback``). The row is keyed by
provider (``google``) so Gmail, Calendar, and Drive all share the same
credential set.

The value is loaded into the process environment (``GOOGLE_REFRESH_TOKEN``)
at startup and after a successful callback, so the existing connectors —
which read configuration exclusively from the environment — keep working
unchanged. The token is never returned by any API response and never
written to the ``integrations`` registry table.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GoogleOAuthCredential(Base):
    """Persisted Google OAuth refresh token (one row per provider)."""

    __tablename__ = "google_oauth_credentials"

    #: OAuth provider key (``google`` today; the shared credential set).
    provider: Mapped[str] = mapped_column(String(60), primary_key=True)
    #: Refresh token obtained from the authorization code exchange.
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    #: Scopes the refresh token was granted for.
    scopes: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
