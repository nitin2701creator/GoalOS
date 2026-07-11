from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.objective import ObjectiveResponse


class GoalCreateRequest(BaseModel):
    company_id: Optional[UUID] = None
    title: str
    description: str
    executive_owner: str
    department: str
    priority: str
    target_date: Optional[date] = None


class GoalUpdateRequest(BaseModel):
    company_id: Optional[UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None
    executive_owner: Optional[str] = None
    department: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    target_date: Optional[date] = None


class GoalResponse(BaseModel):
    id: UUID
    company_id: Optional[UUID]
    title: str
    description: str
    executive_owner: str
    department: str
    priority: str
    status: str
    target_date: Optional[date]
    objective_count: int
    completed_objective_count: int
    progress_percentage: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GoalSummaryResponse(BaseModel):
    goal: GoalResponse
    objectives: List[ObjectiveResponse]
    objective_count: int
    completed_objective_count: int
    progress_percentage: int

    model_config = {"from_attributes": True}
