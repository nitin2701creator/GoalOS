from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.agents.permissions import Permission


class TaskCreateRequest(BaseModel):
    project_id: UUID
    title: str
    description: str
    assigned_agent: Optional[str] = None
    required_integration: Optional[str] = None
    required_capability: Optional[str] = None
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
    required_integration: Optional[str] = None
    required_capability: Optional[str] = None
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
    required_integration: Optional[str] = None
    required_capability: Optional[str] = None
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

    model_config = {"from_attributes": True}


class TaskSummaryResponse(BaseModel):
    task: TaskResponse
    estimated_hours: Optional[float]
    actual_hours: Optional[float]
    remaining_hours: Optional[float]
    is_overdue: bool

    model_config = {"from_attributes": True}


class TaskExecuteRequest(BaseModel):
    """Execute the integration a task requires.

    ``capability`` optionally overrides the task's declared
    ``required_capability``; ``params`` are the capability parameters and
    ``permissions`` are the explicitly granted permissions of the calling
    agent/operator — never escalated implicitly.
    """

    capability: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    permissions: list[Permission] = Field(default_factory=list)
