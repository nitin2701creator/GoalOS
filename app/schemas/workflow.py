from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class WorkflowCreateRequest(BaseModel):
    project_id: UUID
    name: str
    status: Optional[str] = None
    progress_percentage: Optional[int] = None


class WorkflowUpdateRequest(BaseModel):
    project_id: Optional[UUID] = None
    name: Optional[str] = None
    status: Optional[str] = None
    progress_percentage: Optional[int] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class WorkflowResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    status: str
    progress_percentage: int
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
