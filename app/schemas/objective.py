from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ObjectiveCreateRequest(BaseModel):
    goal_id: UUID
    title: str
    description: str
    status: Optional[str] = None


class ObjectiveUpdateRequest(BaseModel):
    goal_id: Optional[UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ObjectiveResponse(BaseModel):
    id: UUID
    goal_id: UUID
    title: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
