from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.repositories.goal_repository import GoalRepository
from app.services.goal_service import GoalService
from app.schemas.goal import (
    GoalCreateRequest,
    GoalResponse,
    GoalSummaryResponse,
    GoalUpdateRequest,
)
from app.schemas.objective import ObjectiveResponse

router = APIRouter()


def _get_service(db=Depends(get_db)) -> GoalService:
    repo = GoalRepository(db)
    return GoalService(repo)


@router.get("", response_model=List[GoalResponse])
def list_goals(service: GoalService = Depends(_get_service)):
    return service.list()


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal(goal_id: UUID, service: GoalService = Depends(_get_service)):
    result = service.get(goal_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return result


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal(request: GoalCreateRequest, service: GoalService = Depends(_get_service)):
    return service.create(request)


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: UUID, request: GoalUpdateRequest, service: GoalService = Depends(_get_service)
):
    result = service.update(goal_id, request)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return result


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: UUID, service: GoalService = Depends(_get_service)):
    ok = service.delete(goal_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")


@router.get("/{goal_id}/summary", response_model=GoalSummaryResponse)
def goal_summary(goal_id: UUID, service: GoalService = Depends(_get_service)):
    result = service.summary(goal_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return result


@router.get("/{goal_id}/objectives", response_model=List[ObjectiveResponse])
def goal_objectives(goal_id: UUID, service: GoalService = Depends(_get_service)):
    result = service.objectives(goal_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return result
