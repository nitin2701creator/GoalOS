"""Social media database models for GoalOS.

Stores connected social accounts, published posts, and engagement metrics.
Platform-independent fields plus platform-specific metadata as JSON.
OAuth tokens are stored in ``SocialAccount.access_token`` / ``refresh_token``
but never logged or returned in API responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


class SocialAccountStatus(str):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DISCONNECTED = "disconnected"


class SocialAccount(Base):
    """A connected social media account (Facebook Page, Instagram, LinkedIn, etc.)."""

    __tablename__ = "social_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    account_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    account_type: Mapped[str] = mapped_column(String(32), nullable=False, default="page")
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    # OAuth credentials — never logged, never returned in API responses
    access_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Platform-specific metadata (JSON)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    posts: Mapped[list[SocialPost]] = relationship(
        "SocialPost", back_populates="account", cascade="all, delete-orphan"
    )
    metrics: Mapped[list[SocialMetric]] = relationship(
        "SocialMetric", back_populates="account", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_social_account"),
    )


class SocialPost(Base):
    """A published or drafted social media post."""

    __tablename__ = "social_posts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("social_accounts.id"), nullable=False, index=True
    )
    provider_post_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    platform_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Scheduled publishing
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Platform-specific payload (JSON)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    account: Mapped[SocialAccount] = relationship("SocialAccount", back_populates="posts")


class SocialMetric(Base):
    """Engagement metrics snapshot for a social post or account."""

    __tablename__ = "social_metrics"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("social_accounts.id"), nullable=False, index=True
    )
    post_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("social_posts.id"), nullable=True, index=True
    )
    metric_type: Mapped[str] = mapped_column(String(32), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Raw metrics from the platform (JSON)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    account: Mapped[SocialAccount] = relationship("SocialAccount", back_populates="metrics")
