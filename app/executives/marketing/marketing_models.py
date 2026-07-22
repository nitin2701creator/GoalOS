"""Pydantic models owned by the Marketing executive."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def _identifier() -> str:
    return uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MarketingCampaign(BaseModel):
    id: str = Field(default_factory=_identifier)
    name: str
    objective: str
    channel: str
    status: Literal["draft", "active", "paused", "archived"] = "draft"
    audience_ids: list[str] = Field(default_factory=list)
    budget: float = Field(default=0.0, ge=0)
    spend: float = Field(default=0.0, ge=0)
    revenue: float = Field(default=0.0, ge=0)
    created_at: datetime = Field(default_factory=_now)


class MarketingKPI(BaseModel):
    name: str
    value: float
    target: float | None = None
    unit: str = ""
    trend: Literal["up", "down", "flat"] = "flat"


class AudienceSegment(BaseModel):
    id: str = Field(default_factory=_identifier)
    name: str
    description: str
    estimated_size: int | None = Field(default=None, ge=0)
    criteria: dict[str, object] = Field(default_factory=dict)


class CreativeAsset(BaseModel):
    id: str = Field(default_factory=_identifier)
    name: str
    asset_type: Literal["image", "video", "copy", "landing_page", "other"]
    channel: str | None = None
    url: str | None = None
    status: Literal["draft", "approved", "active", "archived"] = "draft"


class BudgetPlan(BaseModel):
    campaign_id: str | None = None
    total_budget: float = Field(ge=0)
    daily_budget: float | None = Field(default=None, ge=0)
    currency: str = "USD"
    allocation: dict[str, float] = Field(default_factory=dict)


class CampaignRecommendation(BaseModel):
    id: str = Field(default_factory=_identifier)
    campaign_id: str | None = None
    title: str
    rationale: str
    action: str
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class MarketingSummary(BaseModel):
    campaign_count: int = 0
    active_campaign_count: int = 0
    total_budget: float = 0.0
    total_spend: float = 0.0
    total_revenue: float = 0.0
    kpis: list[MarketingKPI] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_now)
