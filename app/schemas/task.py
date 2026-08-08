from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class TaskCreateRequest(BaseModel):
    project_id: UUID
    title: str
    description: str
    assigned_agent: Optional[str] = None
    status: Optional[str] = None
    priority: str
    workflow_id: Optional[UUID] = None
    sequence_number: Optional[int] = None
    depends_on_task_id: Optional[UUID] = None
    execution_order: Optional[int] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    due_date: Optional[date] = None
    result: Optional[str] = None


class TaskUpdateRequest(BaseModel):
    project_id: Optional[UUID] = None
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_agent: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    workflow_id: Optional[UUID] = None
    sequence_number: Optional[int] = None
    depends_on_task_id: Optional[UUID] = None
    execution_order: Optional[int] = None
    estimated_hours: Optional[float] = None
    actual_hours: Optional[float] = None
    due_date: Optional[date] = None
    result: Optional[str] = None


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    assigned_agent: Optional[str]
    status: str
    priority: str
    workflow_id: Optional[UUID]
    sequence_number: Optional[int]
    depends_on_task_id: Optional[UUID]
    execution_order: Optional[int]
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    due_date: Optional[date]
    result: Optional[str]
    created_at: datetime
    updated_at: datetime
    worker_id: Optional[UUID] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    model_config = {"from_attributes": True}


class TaskSummaryResponse(BaseModel):
    task: TaskResponse
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    remaining_hours: Optional[float]
    is_overdue: bool

    model_config = {"from_attributes": True}
