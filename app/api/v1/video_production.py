"""Video production API endpoints.

Endpoints for creating, managing, and monitoring video production jobs
powered by OpenMontage.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID

from app.db.session import get_db
from app.schemas.video_production import (
    VideoPipelineInfo,
    VideoProductionListResponse,
    VideoProductionRequest,
    VideoProductionResponse,
    VideoProductionUpdateRequest,
)
from app.services.video_service import VideoProductionService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> VideoProductionService:
    return VideoProductionService(db)


# ------------------------------------------------------------------
# Pipelines
# ------------------------------------------------------------------

@router.get("/pipelines", response_model=list[VideoPipelineInfo])
def list_pipelines(service: VideoProductionService = Depends(_get_service)):
    """List available video production pipelines."""
    return service.get_available_pipelines()


@router.get("/status")
def provider_status(service: VideoProductionService = Depends(_get_service)):
    """Return OpenMontage provider configuration and status."""
    return service.get_provider_status()


# ------------------------------------------------------------------
# Jobs
# ------------------------------------------------------------------

@router.post("", response_model=VideoProductionResponse, status_code=201)
def create_production(
    request: VideoProductionRequest,
    service: VideoProductionService = Depends(_get_service),
):
    """Create a new video production job."""
    job = service.create_job(request)
    return VideoProductionResponse.model_validate(job)


@router.get("", response_model=VideoProductionListResponse)
def list_productions(
    job_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    service: VideoProductionService = Depends(_get_service),
):
    """List video production jobs."""
    jobs = service.list_jobs(status=job_status, limit=limit, offset=offset)
    total = service.count_jobs(status=job_status)
    return VideoProductionListResponse(
        productions=[VideoProductionResponse.model_validate(j) for j in jobs],
        total=total,
    )


@router.get("/{job_id}", response_model=VideoProductionResponse)
def get_production(
    job_id: UUID,
    service: VideoProductionService = Depends(_get_service),
):
    """Get a video production job by ID."""
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Production not found")
    return VideoProductionResponse.model_validate(job)


@router.post("/{job_id}/start")
def start_production(
    job_id: UUID,
    service: VideoProductionService = Depends(_get_service),
):
    """Start production on a queued/approved job."""
    result = service.start_job(job_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{job_id}/approve")
def approve_production(
    job_id: UUID,
    service: VideoProductionService = Depends(_get_service),
):
    """Approve a job that is awaiting approval."""
    result = service.approve_job(job_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{job_id}/cancel")
def cancel_production(
    job_id: UUID,
    service: VideoProductionService = Depends(_get_service),
):
    """Cancel a running/queued job."""
    result = service.cancel_job(job_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{job_id}/retry")
def retry_production(
    job_id: UUID,
    service: VideoProductionService = Depends(_get_service),
):
    """Retry a failed job."""
    result = service.retry_job(job_id)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/{job_id}/poll")
def poll_production(
    job_id: UUID,
    service: VideoProductionService = Depends(_get_service),
):
    """Poll the current status of a production job."""
    result = service.poll_status(job_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result
