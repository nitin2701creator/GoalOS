from __future__ import annotations

import os
from pathlib import Path
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.kernel.development.executors import create_coding_executor
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.execution import (
    ExecutionCompleteRequest,
    ExecutionCreateRequest,
    ExecutionFailRequest,
    ExecutionResponse,
    ExecutionUpdateRequest,
    TaskExecuteRequest,
)
from app.services.execution_service import ExecutionService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ExecutionService:
    repo = ExecutionRepository(db)
    return ExecutionService(repo, TaskRepository(db))


def _repository_path() -> Path:
    """Return the repository root CLI workers should run in."""
    configured = os.getenv("GOALOS_REPOSITORY")
    return Path(configured) if configured else Path.cwd()


@router.get("/executions", response_model=List[ExecutionResponse])
def list_executions(service: ExecutionService = Depends(_get_service)):
    return service.list_executions()


@router.post("/executions", response_model=ExecutionResponse, status_code=status.HTTP_201_CREATED)
def create_execution(
    request: ExecutionCreateRequest, service: ExecutionService = Depends(_get_service)
):
    try:
        return service.create_execution(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
def get_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    result = service.get(execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.patch("/executions/{execution_id}", response_model=ExecutionResponse)
def update_execution(
    execution_id: UUID,
    request: ExecutionUpdateRequest,
    service: ExecutionService = Depends(_get_service),
):
    result = service.update_execution(execution_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.delete("/executions/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    ok = service.delete_execution(execution_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")


@router.get("/tasks/{task_id}/executions", response_model=List[ExecutionResponse])
def get_task_executions(task_id: UUID, service: ExecutionService = Depends(_get_service)):
    return service.list_task_executions(task_id)


@router.post(
    "/tasks/{task_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Execute a task end to end",
    description=(
        "Submit a task for execution, claim it for the named worker, run the "
        "worker, verify the result, and persist the execution outcome, "
        "verification verdict, and final task status."
    ),
)
def execute_task(
    task_id: UUID,
    request: TaskExecuteRequest,
    service: ExecutionService = Depends(_get_service),
):
    """Execute a persisted task through the full worker lifecycle."""
    try:
        return service.run_task(
            task_id,
            request.agent_name,
            worker_type=request.worker_type,
            repository=_repository_path(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/tasks/{task_id}/autonomous-execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run a task through the autonomous development loop",
    description=(
        "Inspect the repository, plan the change, implement it, run the test "
        "suite, repair failures within a bounded attempt limit, review, and "
        "commit only after verification passes. Every state transition and "
        "artifact (state, attempts, test results, errors, review results, "
        "result, commit hash) is persisted on the execution."
    ),
)
def execute_task_autonomously(
    task_id: UUID,
    request: TaskExecuteRequest,
    service: ExecutionService = Depends(_get_service),
):
    """Execute a persisted task through the autonomous development loop."""
    repository = _repository_path()
    executor = None
    if request.executor:
        try:
            executor = create_coding_executor(request.executor, repository=repository)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
    try:
        return service.run_autonomous(
            task_id,
            request.agent_name,
            worker_type=request.worker_type,
            executor=executor,
            repository=repository,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/executions/{execution_id}/start", response_model=ExecutionResponse)
def start_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    result = service.start_execution(execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.post("/executions/{execution_id}/complete", response_model=ExecutionResponse)
def complete_execution(
    execution_id: UUID,
    request: ExecutionCompleteRequest,
    service: ExecutionService = Depends(_get_service),
):
    result = service.complete_execution(execution_id, request.result)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.post("/executions/{execution_id}/fail", response_model=ExecutionResponse)
def fail_execution(
    execution_id: UUID,
    request: ExecutionFailRequest,
    service: ExecutionService = Depends(_get_service),
):
    result = service.fail_execution(execution_id, request.error_message)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result


@router.post("/executions/{execution_id}/retry", response_model=ExecutionResponse)
def retry_execution(execution_id: UUID, service: ExecutionService = Depends(_get_service)):
    result = service.retry_execution(execution_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Execution not found")
    return result
