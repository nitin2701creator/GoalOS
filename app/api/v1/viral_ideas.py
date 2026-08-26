"""Viral Idea Finder API endpoints for GoalOS.

Provides read access to viral ideas and content items, and a scan
trigger endpoint for refreshing the data.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.db.session import get_db
from app.repositories.viral_repository import ViralRepository
from app.schemas.viral import (
    ScanRequest,
    ScanResponse,
    ViralContentItemResponse,
    ViralIdeaResponse,
)
from app.services.viral_service import ViralService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ViralService:
    repo = ViralRepository(db)
    return ViralService(repo)


@router.get("/ideas", response_model=list[ViralIdeaResponse])
def list_ideas(
    query: Optional[str] = Query(None, description="Filter by topic keyword"),
    source: Optional[str] = Query(None, description="Filter by source platform"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    min_score: float = Query(0.0, description="Minimum viral score"),
    limit: int = Query(50, ge=1, le=200),
    service: ViralService = Depends(_get_service),
):
    """List viral ideas ordered by score."""
    return service.list_ideas(
        query=query, source=source, topic=topic, min_score=min_score, limit=limit
    )


@router.get("/ideas/{idea_id}", response_model=ViralIdeaResponse)
def get_idea(
    idea_id: str,
    service: ViralService = Depends(_get_service),
):
    """Get a single viral idea by ID."""
    result = service.get_idea(idea_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Idea not found"
        )
    return result


@router.get("/items", response_model=list[ViralContentItemResponse])
def list_content_items(
    source: Optional[str] = Query(None, description="Filter by source"),
    topic: Optional[str] = Query(None, description="Filter by topic"),
    limit: int = Query(100, ge=1, le=500),
    service: ViralService = Depends(_get_service),
):
    """List collected content items."""
    return service.list_content_items(source=source, topic=topic, limit=limit)


@router.post("/scan", response_model=ScanResponse, status_code=status.HTTP_201_CREATED)
async def trigger_scan(
    request: ScanRequest,
    service: ViralService = Depends(_get_service),
):
    """Trigger a fresh viral scan across configured sources."""
    return await service.scan(request)
