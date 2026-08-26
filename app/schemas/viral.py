"""Pydantic schemas for the Viral Idea Finder API."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ViralContentItemResponse(BaseModel):
    """Response model for a collected content item."""

    id: str
    source: str
    source_url: str
    title: str
    description: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    collected_at: datetime
    topic: Optional[str] = None
    language: Optional[str] = None
    engagement: Optional[dict] = None
    metadata_json: Optional[dict] = None

    model_config = {"from_attributes": True}


class ViralIdeaResponse(BaseModel):
    """Response model for a scored viral idea."""

    id: str
    title: str
    summary: str
    topic: Optional[str] = None
    source_platforms: Optional[list[str]] = None
    source_item_ids: Optional[list[str]] = None
    viral_score: float
    novelty_score: float
    momentum_score: float
    cross_source_score: float
    engagement_score: float
    evidence: Optional[list[str]] = None
    why_it_matters: str
    suggested_angles: Optional[list[str]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanRequest(BaseModel):
    """Request to trigger a fresh viral scan."""

    query: str
    sources: Optional[list[str]] = None
    max_items_per_source: int = 20


class ScanResponse(BaseModel):
    """Response after triggering a scan."""

    items_collected: int
    ideas_generated: int
    sources_used: list[str]
    message: str
