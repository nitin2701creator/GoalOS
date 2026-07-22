"""Pydantic models exchanged through the GoalOS executive runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _new_identifier() -> str:
    """Return a stable identifier for an executive runtime record."""

    return str(uuid4())


def _utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class ExecutiveModel(BaseModel):
    """Common validated fields used by executive runtime responses."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(default_factory=_new_identifier, min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    status: str = Field(default="unknown", min_length=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutiveSummary(ExecutiveModel):
    """A concise, normalized status summary from one executive."""

    executive_name: str = Field(min_length=1)


class ExecutiveKPI(ExecutiveModel):
    """A measurable executive key performance indicator."""

    value: float | int | str | None = None
    target: float | int | str | None = None
    unit: str | None = None
    measured_at: datetime = Field(default_factory=_utc_now)


class ExecutiveAlert(ExecutiveModel):
    """An issue or risk that needs executive attention."""

    severity: str = Field(default="medium", min_length=1)
    status: str = Field(default="active", min_length=1)
    occurred_at: datetime = Field(default_factory=_utc_now)


class ExecutivePriority(ExecutiveModel):
    """A ranked item of executive work."""

    priority: int = Field(default=3, ge=1, le=5)
    due_at: datetime | None = None


class ExecutiveRecommendation(ExecutiveModel):
    """A proposed decision or action from an executive."""

    priority: int = Field(default=3, ge=1, le=5)
    status: str = Field(default="proposed", min_length=1)
    recommended_at: datetime = Field(default_factory=_utc_now)
