"""Viral Idea Finder database models for GoalOS.

Stores collected content items from various sources and the generated
viral ideas with scoring evidence.  All engagement metrics are stored
as JSON so different source formats can coexist without schema churn.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base


class ViralContentItem(Base):
    """A single normalized content item collected from a source."""

    __tablename__ = "viral_content_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    author: Mapped[str | None] = mapped_column(String(256), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    engagement: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ViralIdea(Base):
    """A deduplicated, scored viral idea derived from one or more content items."""

    __tablename__ = "viral_ideas"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    topic: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_platforms: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_item_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Scores (0.0 - 1.0 range)
    viral_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cross_source_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    engagement_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Evidence and suggestions
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggested_angles: Mapped[list | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
