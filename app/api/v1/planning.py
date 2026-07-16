"""Planning API endpoints for AI planning generation."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status

from app.llm.provider_factory import ProviderFactory
from app.schemas.planning import PlanningRequest, PlanningResponse
from app.services.planning_service import PlanningService

router = APIRouter()


def _get_service() -> PlanningService:
    """Dependency to provide a PlanningService instance.
    
    Returns:
        Configured PlanningService with LLM provider.
    """
    provider = ProviderFactory.create()
    return PlanningService(provider)


@router.post(
    "/generate",
    response_model=PlanningResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a complete plan",
    description="Generate a comprehensive plan from vision, mission, goals, and constraints.",
)
def generate_planning(
    request: PlanningRequest,
    service: PlanningService = Depends(_get_service),
) -> PlanningResponse:
    """Generate a complete plan from a planning request.
    
    Args:
        request: PlanningRequest with vision, mission, goals, and constraints.
        service: Injected PlanningService instance.
        
    Returns:
        PlanningResponse with all generated artifacts.
        
    Raises:
        HTTPException: 400 Bad Request if the request is invalid.
    """
    try:
        return service.generate(request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/preview",
    response_model=PlanningResponse,
    status_code=status.HTTP_200_OK,
    summary="Preview a plan without persisting",
    description="Generate a preview plan from query parameters.",
)
def preview_planning(
    vision: str = Query(..., description="Long-term business vision"),
    mission: str = Query(..., description="Operating mission"),
    business_goals: list[str] = Query(..., description="List of business goals"),
    constraints: list[str] | None = Query(None, description="Optional constraints"),
    service: PlanningService = Depends(_get_service),
) -> PlanningResponse:
    """Preview a plan based on query parameters.
    
    Args:
        vision: Long-term business vision.
        mission: Operating mission.
        business_goals: List of business goals to achieve.
        constraints: Optional list of constraints.
        service: Injected PlanningService instance.
        
    Returns:
        PlanningResponse with all generated artifacts.
        
    Raises:
        HTTPException: 400 Bad Request if parameters are invalid.
    """
    try:
        return service.preview(vision, mission, business_goals, constraints)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{goal_id}",
    response_model=PlanningResponse,
    status_code=status.HTTP_200_OK,
    summary="Get plan filtered by goal ID",
    description="Generate and filter a plan for a specific goal.",
)
def get_planning_by_goal(
    goal_id: UUID = Path(..., description="Goal ID to filter by"),
    vision: str = Query(..., description="Long-term business vision"),
    mission: str = Query(..., description="Operating mission"),
    business_goals: list[str] = Query(..., description="List of business goals"),
    constraints: list[str] | None = Query(None, description="Optional constraints"),
    service: PlanningService = Depends(_get_service),
) -> PlanningResponse:
    """Get planning filtered by a specific goal ID.
    
    Args:
        goal_id: The goal ID to filter by.
        vision: Long-term business vision.
        mission: Operating mission.
        business_goals: List of business goals.
        constraints: Optional list of constraints.
        service: Injected PlanningService instance.
        
    Returns:
        PlanningResponse filtered to the specified goal.
        
    Raises:
        HTTPException: 400 Bad Request if parameters are invalid.
        HTTPException: 404 Not Found if goal_id is not found.
    """
    try:
        return service.get_by_goal(str(goal_id), vision, mission, business_goals, constraints)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
