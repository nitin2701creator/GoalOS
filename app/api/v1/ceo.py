"""
CEO API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.engines.ceo_planning_engine import ceo_planning_engine
from app.schemas.ceo import CEOPlanRequest, CEOPlanResponse

router = APIRouter(prefix="/ceo", tags=["CEO"])


@router.post("/plan", response_model=CEOPlanResponse)
async def create_ceo_plan(request: CEOPlanRequest) -> CEOPlanResponse:
    """Create a structured executive plan for a business goal."""
    return ceo_planning_engine.create_plan(request.goal)
