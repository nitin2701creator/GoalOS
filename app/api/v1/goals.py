"""
Goal API endpoints.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.goal_repository import GoalRepository
from app.schemas.goal import GoalCreateRequest, GoalResponse, GoalUpdateRequest
from app.services.goal_service import GoalService

router = APIRouter(prefix="/goals", tags=["Goals"])


def get_goal_service(db: Session = Depends(get_db)) -> GoalService:
    """Build a goal service for the current request."""
    return GoalService(GoalRepository(db))


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal(
    request: GoalCreateRequest,
    service: GoalService = Depends(get_goal_service),
) -> GoalResponse:
    """Create a permanent goal."""
    return service.create(request)


@router.get("", response_model=list[GoalResponse])
async def list_goals(service: GoalService = Depends(get_goal_service)) -> list[GoalResponse]:
    """List permanent goals."""
    return list(service.list())


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: uuid.UUID,
    service: GoalService = Depends(get_goal_service),
) -> GoalResponse:
    """Get a permanent goal by ID."""
    goal = service.get(goal_id)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal(
    goal_id: uuid.UUID,
    request: GoalUpdateRequest,
    service: GoalService = Depends(get_goal_service),
) -> GoalResponse:
    """Update a permanent goal."""
    goal = service.update(goal_id, request)
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal(
    goal_id: uuid.UUID,
    service: GoalService = Depends(get_goal_service),
) -> Response:
    """Delete a permanent goal."""
    deleted = service.delete(goal_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
