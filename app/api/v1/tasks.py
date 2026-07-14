from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from app.services.task_service import TaskService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> TaskService:
    repo = TaskRepository(db)
    return TaskService(repo)


@router.get("", response_model=List[TaskResponse])
def list_tasks(service: TaskService = Depends(_get_service)):
    return service.list()


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: UUID, service: TaskService = Depends(_get_service)):
    result = service.get(task_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return result


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(request: TaskCreateRequest, service: TaskService = Depends(_get_service)):
    return service.create(request)


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: UUID,
    request: TaskUpdateRequest,
    service: TaskService = Depends(_get_service),
):
    result = service.update(task_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return result


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: UUID, service: TaskService = Depends(_get_service)):
    ok = service.delete(task_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


@router.get("/project/{project_id}", response_model=List[TaskResponse])
def list_tasks_by_project(project_id: UUID, service: TaskService = Depends(_get_service)):
    result = service.list_by_project(project_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return result


@router.get("/{task_id}/summary", response_model=TaskSummaryResponse)
def get_task_summary(task_id: UUID, service: TaskService = Depends(_get_service)):
    result = service.summary(task_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return result
