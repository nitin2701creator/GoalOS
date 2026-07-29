from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.objective_repository import ObjectiveRepository
from app.services.objective_service import ObjectiveService
from app.schemas.objective import (
    ObjectiveCreateRequest,
    ObjectiveResponse,
    ObjectiveUpdateRequest,
)

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ObjectiveService:
    repo = ObjectiveRepository(db)
    return ObjectiveService(repo)


@router.get("", response_model=List[ObjectiveResponse])
def list_objectives(service: ObjectiveService = Depends(_get_service)):
    return service.list()


@router.get("/{objective_id}", response_model=ObjectiveResponse)
def get_objective(objective_id: UUID, service: ObjectiveService = Depends(_get_service)):
    result = service.get(objective_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
    return result


@router.post("", response_model=ObjectiveResponse, status_code=status.HTTP_201_CREATED)
def create_objective(request: ObjectiveCreateRequest, service: ObjectiveService = Depends(_get_service)):
    return service.create(request)


@router.patch("/{objective_id}", response_model=ObjectiveResponse)
def update_objective(
    objective_id: UUID, request: ObjectiveUpdateRequest, service: ObjectiveService = Depends(_get_service)
):
    result = service.update(objective_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
    return result


@router.delete("/{objective_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_objective(objective_id: UUID, service: ObjectiveService = Depends(_get_service)):
    ok = service.delete(objective_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
