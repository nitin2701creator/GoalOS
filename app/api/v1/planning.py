from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status

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
