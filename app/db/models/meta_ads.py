"""Meta Ads campaign data models for GoalOS.

Normalized models for Meta Marketing API entities: campaigns, ad sets,
ads, creatives, audiences, performance snapshots, and execution actions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CampaignObjective(str, Enum):
    AWARENESS = "OUT_OF_AWARENESS"
    REACH = "REACH"
    TRAFFIC = "OUTBOUND_CLICKS"
    ENGAGEMENT = "ENGAGEMENT"
    LEADS = "LEADS"
    APP_PROMOTION = "APP_PROMOTION"
    SALES = "SALES"
    VIDEO_VIEWS = "THRUPLAY"


class AdsetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"


class ExecutionMode(str, Enum):
    SAFE = "safe"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


class ActionType(str, Enum):
    CREATE_CAMPAIGN = "create_campaign"
    CREATE_ADSET = "create_adset"
    CREATE_AD = "create_ad"
    CREATE_CREATIVE = "create_creative"
    UPDATE_CAMPAIGN = "update_campaign"
    UPDATE_ADSET = "update_adset"
    UPDATE_AD = "update_ad"
    ACTIVATE = "activate"
    PAUSE = "pause"
    INCREASE_BUDGET = "increase_budget"
    DECREASE_BUDGET = "decrease_budget"
    DUPLICATE = "duplicate"


class ActionStatus(str, Enum):
    DRY_RUN = "dry_run"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MetaCampaign(Base):
    """Normalized Meta campaign record."""

    __tablename__ = "meta_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    meta_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    objective: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PAUSED")
    daily_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    lifetime_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stop_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetaAdSet(Base):
    """Normalized Meta ad set record."""

    __tablename__ = "meta_adsets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    meta_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    campaign_meta_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PAUSED")
    daily_budget: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid_strategy: Mapped[str | None] = mapped_column(String(64), nullable=True)
    targeting_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    optimization_goal: Mapped[str | None] = mapped_column(String(64), nullable=True)
    billing_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetaAd(Base):
    """Normalized Meta ad record."""

    __tablename__ = "meta_ads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    meta_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    adset_meta_id: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_meta_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PAUSED")
    creative_meta_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MetaPerformanceSnapshot(Base):
    """Performance snapshot for a Meta entity (campaign/adset/ad)."""

    __tablename__ = "meta_performance_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_meta_id: Mapped[str] = mapped_column(String(64), nullable=False)
    date_start: Mapped[str] = mapped_column(String(10), nullable=False)
    date_stop: Mapped[str] = mapped_column(String(10), nullable=False)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    spend: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reach: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ctr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cpc: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cpm: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frequency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    conversions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    roas: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetaExecutionAction(Base):
    """A pending or completed Meta Ads execution action."""

    __tablename__ = "meta_execution_actions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_meta_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="dry_run")
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="safe")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dry_run_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    budget_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    budget_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    executed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MetaAuditLog(Base):
    """Immutable audit log for Meta Ads operations."""

    __tablename__ = "meta_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    action_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entity_meta_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    meta_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
