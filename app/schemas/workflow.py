from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class WorkflowCreateRequest(BaseModel):
    project_id: UUID
    name: str
    status: str | None = None
    progress_percentage: int | None = None


class WorkflowUpdateRequest(BaseModel):
    project_id: UUID | None = None
    name: str | None = None
    status: str | None = None
    progress_percentage: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class AgentWorkflowRunRequest(BaseModel):
    """Request to run an agent workflow against a workflow."""

    requirement: str = Field(min_length=1)


class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    status: str
    progress_percentage: int
    started_at: datetime | None
    completed_at: datetime | None
    requirement: str | None = None
    resolved_capabilities: list[str] | None = None
    plan: list[dict[str, Any]] | None = None
    steps: list[dict[str, Any]] | None = None
    results: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    error_message: str | None = None
    schedule: str | None = None
    schedule_enabled: bool = False
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    scheduled_from_id: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("schedule_enabled", mode="before")
    @classmethod
    def _coerce_schedule_enabled(cls, value: object) -> object:
        """Treat legacy NULL rows (pre-migration) as disabled."""
        return False if value is None else value
