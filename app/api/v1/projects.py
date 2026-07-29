from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import (
    ProjectCreateRequest,
    ProjectResponse,
    ProjectSummaryResponse,
    ProjectUpdateRequest,
)
from app.services.project_service import ProjectService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ProjectService:
    repo = ProjectRepository(db)
    return ProjectService(repo)


@router.get("", response_model=List[ProjectResponse])
def list_projects(service: ProjectService = Depends(_get_service)):
    return service.list()


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: UUID,
    service: ProjectService = Depends(_get_service),
):
    result = service.get(project_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return result


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ProjectCreateRequest,
    service: ProjectService = Depends(_get_service),
):
    return service.create(request)


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    service: ProjectService = Depends(_get_service),
):
    result = service.update(project_id, request)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return result


@router.get("/{project_id}/summary", response_model=ProjectSummaryResponse)
def get_project_summary(
    project_id: UUID,
    service: ProjectService = Depends(_get_service),
):
    result = service.summary(project_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return result


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: UUID,
    service: ProjectService = Depends(_get_service),
):
    ok = service.delete(project_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )