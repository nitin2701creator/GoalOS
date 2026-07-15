from __future__ import annotations

from uuid import UUID
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.llm.provider_factory import ProviderFactory
from app.schemas.planning import PlanningRequest, PlanningResponse
from app.services.planning_service import PlanningService

router = APIRouter()


def _get_service() -> PlanningService:
    provider = ProviderFactory.create()
    return PlanningService(provider)


@router.post(
    "/generate",
    response_model=PlanningResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_planning(request: PlanningRequest, service: PlanningService = Depends(_get_service)) -> PlanningResponse:
    try:
        return service.generate(request)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/preview",
    response_model=PlanningResponse,
    status_code=status.HTTP_200_OK,
)
def preview_planning(
    vision: str = Query(...),
    mission: str = Query(...),
    business_goals: list[str] = Query(...),
    constraints: list[str] | None = Query(None),
    service: PlanningService = Depends(_get_service),
) -> PlanningResponse:
    try:
        return service.preview(vision, mission, business_goals, constraints)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/{goal_id}",
    response_model=PlanningResponse,
    status_code=status.HTTP_200_OK,
)
def get_planning_by_goal(
    goal_id: UUID,
    vision: str = Query(...),
    mission: str = Query(...),
    business_goals: list[str] = Query(...),
    constraints: list[str] | None = Query(None),
    service: PlanningService = Depends(_get_service),
) -> PlanningResponse:
    try:
        return service.get_by_goal(str(goal_id), vision, mission, business_goals, constraints)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
