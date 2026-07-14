from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    goal_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    title: str
    description: str
    owner: str
    department: str
    priority: str
    start_date: Optional[date] = None
    target_date: Optional[date] = None


class ProjectUpdateRequest(BaseModel):
    goal_id: Optional[UUID] = None
    company_id: Optional[UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None
    owner: Optional[str] = None
    department: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    target_date: Optional[date] = None


class ProjectResponse(BaseModel):
    id: UUID
    goal_id: Optional[UUID]
    company_id: Optional[UUID]
    title: str
    description: str
    owner: str
    department: str
    priority: str
    status: str
    start_date: Optional[date]
    target_date: Optional[date]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectSummaryResponse(BaseModel):
    project: ProjectResponse
    execution_count: int