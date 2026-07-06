"""
Objective API endpoints.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.goal_repository import GoalRepository
from app.repositories.objective_repository import ObjectiveRepository
from app.schemas.objective import ObjectiveCreateRequest, ObjectiveResponse, ObjectiveUpdateRequest
from app.services.objective_service import ObjectiveService

router = APIRouter(prefix="/objectives", tags=["Objectives"])


def get_objective_service(db: Session = Depends(get_db)) -> ObjectiveService:
    """Build an objective service for the current request."""
    goal_repository = GoalRepository(db)
    return ObjectiveService(goal_repository, ObjectiveRepository(db))


@router.post("", response_model=ObjectiveResponse, status_code=status.HTTP_201_CREATED)
async def create_objective(
    request: ObjectiveCreateRequest,
    service: ObjectiveService = Depends(get_objective_service),
) -> ObjectiveResponse:
    """Create a new objective."""
    objective = service.create(request)
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return objective


@router.get("", response_model=list[ObjectiveResponse])
async def list_objectives(service: ObjectiveService = Depends(get_objective_service)) -> list[ObjectiveResponse]:
    """List objectives."""
    return service.list()


@router.get("/{objective_id}", response_model=ObjectiveResponse)
async def get_objective(
    objective_id: uuid.UUID,
    service: ObjectiveService = Depends(get_objective_service),
) -> ObjectiveResponse:
    """Get an objective by ID."""
    objective = service.get(objective_id)
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
    return objective


@router.put("/{objective_id}", response_model=ObjectiveResponse)
async def update_objective(
    objective_id: uuid.UUID,
    request: ObjectiveUpdateRequest,
    service: ObjectiveService = Depends(get_objective_service),
) -> ObjectiveResponse:
    """Update an objective."""
    objective = service.update(objective_id, request)
    if objective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective or goal not found")
    return objective


@router.delete("/{objective_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_objective(
    objective_id: uuid.UUID,
    service: ObjectiveService = Depends(get_objective_service),
) -> Response:
    """Delete an objective."""
    deleted = service.delete(objective_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Objective not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
