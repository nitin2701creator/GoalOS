"""API schemas for the GoalOS persisted scheduler.

Creating/updating a schedule is a configuration action that changes the
autonomous execution surface, so ``permissions`` must include the
explicit ``SCHEDULE_WORKFLOWS`` grant — the scheduler never bypasses the
existing permission model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.permissions import Permission


class ScheduleCreateRequest(BaseModel):
    """Create (or update) a schedule on an existing workflow."""

    workflow_id: UUID
    schedule: str = Field(min_length=1, max_length=20)
    requirement: str | None = None
    permissions: list[Permission] = Field(default_factory=list)


class ScheduleResponse(BaseModel):
    """A persisted schedule with its run-history summary."""

    workflow_id: UUID
    name: str
    schedule: str | None = None
    enabled: bool = False
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    status: str
    requirement: str | None = None
    run_count: int = 0
    last_run_status: str | None = None


class SchedulerTickResponse(BaseModel):
    """Summary of one scheduler poll (due runs processed)."""

    due: int
    processed: list[dict[str, Any]] = Field(default_factory=list)
