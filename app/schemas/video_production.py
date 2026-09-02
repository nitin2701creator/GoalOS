"""API schemas for the GoalOS video production capability."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class VideoProductionRequest(BaseModel):
    """Normalized video production request."""

    prompt: str = Field(min_length=1, description="Natural language description of the video to create")
    duration_seconds: int | None = Field(default=None, ge=5, le=600, description="Target duration in seconds")
    aspect_ratio: str = Field(default="16:9", description="Video aspect ratio (16:9, 9:16, 1:1, 4:5)")
    style: str | None = Field(default=None, description="Visual style (cinematic, animated, corporate, etc.)")
    audience: str | None = Field(default=None, description="Target audience")
    language: str = Field(default="en", description="Primary language (ISO 639-1)")
    voice: str | None = Field(default=None, description="Voice/tone preference")
    music: bool = Field(default=True, description="Include background music")
    captions: bool = Field(default=True, description="Include subtitles/captions")
    pipeline: str = Field(default="auto", description="Pipeline name or 'auto' for auto-selection")
    provider: str = Field(default="openmontage", description="Video production provider")
    input_assets: dict[str, Any] | None = Field(default=None, description="Input assets (URLs, paths, refs)")
    requires_approval: bool = Field(default=True, description="Require human approval before generation")


class VideoProductionResponse(BaseModel):
    """Response for a video production job."""

    id: UUID
    prompt: str
    duration_seconds: int | None = None
    aspect_ratio: str = "16:9"
    style: str | None = None
    pipeline: str
    provider: str
    status: str
    current_stage: str | None = None
    progress_percent: int = 0
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    output_video_path: str | None = None
    output_thumbnail_path: str | None = None
    output_metadata: dict[str, Any] | None = None
    duration_actual: float | None = None
    resolution: str | None = None
    error_message: str | None = None
    error_stage: str | None = None
    requires_approval: bool = True
    approved: bool = False
    requestor: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class VideoProductionListResponse(BaseModel):
    """List of video production jobs."""

    productions: list[VideoProductionResponse]
    total: int


class VideoProductionUpdateRequest(BaseModel):
    """Update a video production (approve, cancel, etc.)."""

    action: str = Field(description="Action: approve, cancel, retry")
    reason: str | None = Field(default=None, description="Optional reason")


class VideoPipelineInfo(BaseModel):
    """Information about an available video pipeline."""

    name: str
    display_name: str
    description: str
    openmontage_pipeline: str
    typical_duration: str | None = None
    requires_input: bool = False
