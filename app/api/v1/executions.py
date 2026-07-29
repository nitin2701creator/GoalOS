from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.execution_repository import ExecutionRepository
from app.schemas.execution import (
    ExecutionCompleteRequest,
    ExecutionCreateRequest,
    ExecutionFailRequest,
    ExecutionResponse,
    ExecutionUpdateRequest,
)
from app.services.execution_service import ExecutionService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ExecutionService:
    repo = ExecutionRepository(db)
    return ExecutionService(repo)


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
