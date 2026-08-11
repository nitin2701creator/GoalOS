"""API schemas for the Autonomous Development System endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.kernel.development.models import TaskStatus, WorkerType


class DevelopmentRunRequest(BaseModel):
    """Request to plan and execute an objective end to end.

    Attributes:
        objective: The objective to plan and execute.
        worker_type: Optional coding CLI to dispatch tasks to. When set,
            tasks run through the matching installed CLI worker; when the
            CLI is not installed the run halts with a blocked task.
    """

    objective: str = Field(min_length=1, max_length=2000)
    worker_type: WorkerType | None = None


class DevelopmentTaskResponse(BaseModel):
    """API representation of a development task and its final status."""

    id: UUID
    title: str
    description: str
    status: TaskStatus
    worker: WorkerType
    dependencies: list[UUID]
    files: list[str]


class DevelopmentExecutionResponse(BaseModel):
    """API representation of one task execution with its verdict."""

    task_id: UUID
    title: str
    success: bool
    output: str
    verification_passed: bool
    verification_summary: str


class DevelopmentRunResponse(BaseModel):
    """Outcome of an autonomous development run."""

    objective: str
    succeeded: bool
    summary: str
    tasks: list[DevelopmentTaskResponse]
    executions: list[DevelopmentExecutionResponse]
