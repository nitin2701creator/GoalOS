"""
GoalOS API router.
"""

from fastapi import APIRouter

from app.api.v1.ceo import router as ceo_router
from app.api.v1.goals import router as goals_router

router = APIRouter(prefix="/api/v1", tags=["GoalOS"])

router.include_router(ceo_router)
router.include_router(goals_router)


@router.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/info")
async def info() -> dict[str, str]:
    """Application information."""
    return {
        "application": "GoalOS",
        "organization": "Organigram",
        "version": "0.1.0",
    }
