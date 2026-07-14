from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowUpdateRequest,
)
from app.services.workflow_service import WorkflowService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> WorkflowService:
    workflow_repo = WorkflowRepository(db)
    execution_repo = ExecutionRepository(db)
    return WorkflowService(workflow_repo, execution_repo)


@router.get("", response_model=List[WorkflowResponse])
def list_workflows(service: WorkflowService = Depends(_get_service)):
    return service.list()


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    result = service.get(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    request: WorkflowCreateRequest, service: WorkflowService = Depends(_get_service)
):
    return service.create(request)


@router.patch("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    request: WorkflowUpdateRequest,
    service: WorkflowService = Depends(_get_service),
):
    result = service.update(workflow_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    ok = service.delete(workflow_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")


@router.post("/{workflow_id}/start", response_model=WorkflowResponse)
def start_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    result = service.start(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/complete", response_model=WorkflowResponse)
def complete_workflow(workflow_id: UUID, service: WorkflowService = Depends(_get_service)):
    result = service.complete(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/fail", response_model=WorkflowResponse)
def fail_workflow(
    workflow_id: UUID,
    service: WorkflowService = Depends(_get_service),
):
    result = service.fail(workflow_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.post("/{workflow_id}/progress", response_model=WorkflowResponse)
def progress_workflow(
    workflow_id: UUID,
    progress: int,
    service: WorkflowService = Depends(_get_service),
):
    result = service.progress(workflow_id, progress)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    return result


@router.get("/project/{project_id}", response_model=List[WorkflowResponse])
def list_workflows_by_project(
    project_id: UUID, service: WorkflowService = Depends(_get_service)
):
    result = service.list_by_project(project_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result
