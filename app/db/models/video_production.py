"""Video production job model for GoalOS.

Tracks video production requests through the pipeline lifecycle:
QUEUED → PLANNING → AWAITING_APPROVAL → GENERATING → RENDERING →
REVIEWING → COMPLETED / FAILED / CANCELLED

Each job represents one video production request that maps to an
OpenMontage pipeline execution.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VideoJobStatus(str, Enum):
    """Lifecycle states for video production jobs."""

    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    GENERATING = "generating"
    RENDERING = "rendering"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VideoPipeline(str, Enum):
    """Normalized GoalOS video pipelines mapping to OpenMontage pipelines."""

    EXPLAINER = "animated-explainer"
    TALKING_HEAD = "talking-head"
    CINEMATIC = "cinematic"
    CLIP_FACTORY = "clip-factory"
    PODCAST_CLIP = "podcast-repurpose"
    ANIMATION = "animation"
    CHARACTER_ANIMATION = "character-animation"
    HYBRID = "hybrid"
    AVATAR = "avatar-spokesperson"
    LOCALIZATION = "localization-dub"
    SCREEN_DEMO = "screen-demo"
    AUTO = "auto"


class VideoProduction(Base):
    """A video production job tracked by GoalOS."""

    __tablename__ = "video_productions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # -- Request --
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aspect_ratio: Mapped[str] = mapped_column(String(20), nullable=False, default="16:9")
    style: Mapped[str | None] = mapped_column(String(100), nullable=True)
    audience: Mapped[str | None] = mapped_column(String(200), nullable=True)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    voice: Mapped[str | None] = mapped_column(String(100), nullable=True)
    music: Mapped[bool] = mapped_column(default=True, nullable=False)
    captions: Mapped[bool] = mapped_column(default=True, nullable=False)

    # -- Pipeline / Provider --
    pipeline: Mapped[str] = mapped_column(String(60), nullable=False, default="auto")
    provider: Mapped[str] = mapped_column(String(60), nullable=False, default="openmontage")
    project_id_openmontage: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # -- Status / Progress --
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default=VideoJobStatus.QUEUED.value
    )
    current_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- Input Assets --
    input_assets: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # -- Output Artifacts --
    output_video_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    duration_actual: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # -- Cost / Approval --
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    requires_approval: Mapped[bool] = mapped_column(default=True, nullable=False)
    approved: Mapped[bool] = mapped_column(default=False, nullable=False)

    # -- Error --
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # -- Metadata --
    requestor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
