"""
Goal API schemas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalStatus


class GoalCreateRequest(BaseModel):
    """Request body for creating a goal."""

    company_id: uuid.UUID | None = None
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    executive_owner: str = Field(..., min_length=1, max_length=120)
    department: str = Field(..., min_length=1, max_length=120)
    priority: str = Field(..., min_length=1, max_length=50)
    status: GoalStatus = GoalStatus.DRAFT
    target_date: date | None = None


class GoalUpdateRequest(BaseModel):
    """Request body for updating a goal."""

    company_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    executive_owner: str | None = Field(default=None, min_length=1, max_length=120)
    department: str | None = Field(default=None, min_length=1, max_length=120)
    priority: str | None = Field(default=None, min_length=1, max_length=50)
    status: GoalStatus | None = None
    target_date: date | None = None


class GoalResponse(BaseModel):
    """Goal response returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID | None
    title: str
    description: str
    executive_owner: str
    department: str
    priority: str
    status: GoalStatus
    target_date: date | None
    created_at: datetime
    updated_at: datetime
