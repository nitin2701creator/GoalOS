from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class ExecutionCreateRequest(BaseModel):
    task_id: UUID
    agent_name: str
    status: Optional[str] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    execution_logs: Optional[str] = None


class ExecutionUpdateRequest(BaseModel):
    task_id: Optional[UUID] = None
    agent_name: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_duration_seconds: Optional[int] = None
    retry_count: Optional[int] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    execution_logs: Optional[str] = None


class ExecutionResponse(BaseModel):
    id: UUID
    task_id: UUID
    agent_name: str
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    execution_duration_seconds: Optional[int]
    retry_count: int
    result: Optional[str]
    error_message: Optional[str]
    execution_logs: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExecutionCompleteRequest(BaseModel):
    result: Optional[str] = None


class ExecutionFailRequest(BaseModel):
    error_message: str


class ExecutionSummaryResponse(BaseModel):
    total_executions: int
    completed: int
    failed: int
    running: int
    pending: int
    cancelled: int
    retrying: int
    last_execution: Optional[ExecutionResponse]

    model_config = {"from_attributes": True}
