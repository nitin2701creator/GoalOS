"""
Objective API schemas.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.goal import GoalStatus


class ObjectiveCreateRequest(BaseModel):
    """Request body for creating an objective."""

    goal_id: uuid.UUID
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1, max_length=120)
    department: str = Field(..., min_length=1, max_length=120)
    priority: str = Field(..., min_length=1, max_length=50)
    status: GoalStatus = GoalStatus.DRAFT
    target_date: date | None = None
    created_by: str = Field(default="system", min_length=1, max_length=120)
    updated_by: str = Field(default="system", min_length=1, max_length=120)


class ObjectiveUpdateRequest(BaseModel):
    """Request body for updating an objective."""

    goal_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1)
    owner: str | None = Field(default=None, min_length=1, max_length=120)
    department: str | None = Field(default=None, min_length=1, max_length=120)
    priority: str | None = Field(default=None, min_length=1, max_length=50)
    status: GoalStatus | None = None
    target_date: date | None = None
    updated_by: str | None = Field(default=None, min_length=1, max_length=120)


class ObjectiveResponse(BaseModel):
    """Objective response returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    goal_id: uuid.UUID
    title: str
    description: str
    owner: str
    department: str
    priority: str
    status: GoalStatus
    target_date: date | None
    created_by: str
    updated_by: str
    created_at: datetime
    updated_at: datetime
