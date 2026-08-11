"""Autonomous Development System API endpoints."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.kernel.development.models import DevelopmentTask
from app.kernel.development.orchestrator import OrchestrationResult, TaskExecutionRecord
from app.kernel.development.service import DevelopmentService
from app.kernel.development.worker import WorkerRegistry
from app.schemas.development import (
    DevelopmentExecutionResponse,
    DevelopmentRunRequest,
    DevelopmentRunResponse,
    DevelopmentTaskResponse,
)

router = APIRouter()


def _repository_path() -> Path:
    """Return the repository root workers should run in.

    ``GOALOS_REPOSITORY`` overrides the current working directory so
    deployments can point ADS at a checked-out repository explicitly.
    """
    configured = os.getenv("GOALOS_REPOSITORY")
    return Path(configured) if configured else Path.cwd()


def _get_service() -> DevelopmentService:
    """Dependency providing an in-memory ADS service."""
    return DevelopmentService()


def _service_for(request: DevelopmentRunRequest) -> DevelopmentService:
    """Build the ADS service that should run ``request``.

    When the request names a ``worker_type``, the service dispatches tasks
    to the matching CLI worker inside the repository; otherwise it uses
    the in-memory mock worker.
    """
    if request.worker_type is None:
        return _get_service()
    return DevelopmentService(worker_registry=WorkerRegistry(repository=_repository_path()))


def _task_response(task: DevelopmentTask) -> DevelopmentTaskResponse:
    """Map a kernel task onto its API representation."""
    return DevelopmentTaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status,
        worker=task.worker,
        dependencies=list(task.dependencies),
        files=[path.as_posix() for path in task.files],
    )


def _execution_response(record: TaskExecutionRecord) -> DevelopmentExecutionResponse:
    """Map a task execution record onto its API representation."""
    return DevelopmentExecutionResponse(
        task_id=record.task.id,
        title=record.task.title,
        success=record.result.success,
        output=record.result.output,
        verification_passed=record.verification.passed,
        verification_summary=record.verification.summary,
    )


def _run_response(result: OrchestrationResult) -> DevelopmentRunResponse:
    """Map an orchestration result onto its API representation."""
    return DevelopmentRunResponse(
        objective=result.objective,
        succeeded=result.succeeded,
        summary=result.summary,
        tasks=[_task_response(task) for task in result.tasks],
        executions=[_execution_response(record) for record in result.executions],
    )


@router.post(
    "/execute",
    response_model=DevelopmentRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute an objective end to end",
    description=(
        "Plan, schedule, execute, and verify an objective autonomously. "
        "Returns the planned tasks with their final statuses and an audit "
        "trail of every execution and verification verdict."
    ),
)
def execute_objective(
    request: DevelopmentRunRequest,
    service: Annotated[DevelopmentService, Depends(_get_service)],
) -> DevelopmentRunResponse:
    """Execute an objective through the full ADS pipeline.

    A run whose requested CLI worker is unavailable completes with a
    failed run and a blocked task explaining why, so callers keep the
    full audit trail instead of a bare error.
    """
    service = _service_for(request)
    try:
        result = service.run_objective(request.objective, worker_type=request.worker_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _run_response(result)


@router.post(
    "/preview",
    response_model=DevelopmentRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Preview a plan without executing",
    description="Generate a deterministic development plan for an objective without executing any work.",
)
def preview_objective(
    request: DevelopmentRunRequest,
    service: Annotated[DevelopmentService, Depends(_get_service)],
) -> DevelopmentRunResponse:
    """Preview the plan an objective would produce."""
    try:
        result = service.preview_objective(request.objective)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _run_response(result)
