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
    verification_status: Optional[str] = None
    verification_summary: Optional[str] = None
    state: Optional[str] = None
    attempts: Optional[int] = None
    test_results: Optional[str] = None
    errors: Optional[str] = None
    review_results: Optional[str] = None
    commit_hash: Optional[str] = None


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
    verification_status: Optional[str] = None
    verification_summary: Optional[str] = None
    state: Optional[str] = None
    attempts: Optional[int] = None
    test_results: Optional[str] = None
    errors: Optional[str] = None
    review_results: Optional[str] = None
    commit_hash: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskExecuteRequest(BaseModel):
    """Request to submit a task for execution by a named worker or executor.

    Attributes:
        agent_name: The worker/agent identity claiming the task.
        worker_type: Optional coding CLI to dispatch to (``codex``,
            ``aider``, ``claude``, ``openhands``) or ``mock`` for the
            deterministic in-memory worker. When omitted, ``mock`` is used.
        executor: Optional coding executor for autonomous runs: ``native``
            (the GoalOS LLM/provider-backed executor, no external CLI
            required) or ``aider`` (optional development adapter). When
            provided, it takes precedence over ``worker_type`` for
            autonomous execution.
    """

    agent_name: str
    worker_type: Optional[str] = None
    executor: Optional[str] = None


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
