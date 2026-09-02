"""Video production service for GoalOS.

Orchestrates video production jobs through the OpenMontage adapter.
Manages job lifecycle, approval flow, and artifact collection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.video_production import VideoJobStatus, VideoProduction
from app.integrations.video.openmontage_adapter import (
    OpenMontageAdapter,
    OpenMontageConfig,
    PIPELINE_DISPLAY_NAMES,
)
from app.schemas.video_production import (
    VideoPipelineInfo,
    VideoProductionRequest,
    VideoProductionResponse,
)

logger = logging.getLogger(__name__)


class VideoProductionService:
    """Manages video production jobs through OpenMontage."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.config = OpenMontageConfig.from_env()
        self.adapter = OpenMontageAdapter(self.config)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_job(self, request: VideoProductionRequest, requestor: str | None = None) -> VideoProduction:
        """Create a new video production job from a normalized request."""
        job = VideoProduction(
            prompt=request.prompt,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            style=request.style,
            audience=request.audience,
            language=request.language,
            voice=request.voice,
            music=request.music,
            captions=request.captions,
            pipeline=request.pipeline,
            provider=request.provider,
            input_assets=request.input_assets,
            requires_approval=request.requires_approval,
            status=VideoJobStatus.QUEUED.value,
            requestor=requestor,
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        logger.info("Created video production job %s (pipeline=%s)", job.id, job.pipeline)
        return job

    def get_job(self, job_id: UUID) -> VideoProduction | None:
        return self.db.query(VideoProduction).filter(VideoProduction.id == job_id).first()

    def list_jobs(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VideoProduction]:
        query = self.db.query(VideoProduction)
        if status:
            query = query.filter(VideoProduction.status == status)
        return query.order_by(VideoProduction.created_at.desc()).offset(offset).limit(limit).all()

    def count_jobs(self, status: str | None = None) -> int:
        query = self.db.query(VideoProduction)
        if status:
            query = query.filter(VideoProduction.status == status)
        return query.count()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_job(self, job_id: UUID) -> dict[str, Any]:
        """Start production on a queued/awaiting_approval job.

        Creates the OpenMontage project and starts production.
        """
        job = self.get_job(job_id)
        if job is None:
            return {"error": "Job not found"}
        if job.status not in (VideoJobStatus.QUEUED.value, VideoJobStatus.AWAITING_APPROVAL.value):
            return {"error": f"Job is in state '{job.status}', cannot start"}
        if job.requires_approval and not job.approved:
            return {"error": "Job requires approval before starting"}

        if not self.adapter.is_configured:
            return {"error": "OpenMontage not configured — set GOALOS_OPENMONTAGE_PATH"}

        # Create the OpenMontage project
        result = self.adapter.create_project(
            prompt=job.prompt,
            pipeline=job.pipeline,
            duration_seconds=job.duration_seconds,
            aspect_ratio=job.aspect_ratio,
            style=job.style,
            language=job.language,
        )

        if result.get("error"):
            job.status = VideoJobStatus.FAILED.value
            job.error_message = result["error"]
            self.db.commit()
            return result

        # Update job with OpenMontage project info
        job.project_id_openmontage = result["project_id"]
        job.pipeline = result.get("pipeline", job.pipeline)
        job.status = VideoJobStatus.PLANNING.value
        job.current_stage = "idea"
        job.started_at = datetime.now(timezone.utc)
        self.db.commit()

        # Start production
        start_result = self.adapter.start_production(
            project_id=result["project_id"],
            project_path=result["project_path"],
        )

        if start_result.get("error"):
            job.status = VideoJobStatus.FAILED.value
            job.error_message = start_result["error"]
            self.db.commit()
            return start_result

        job.status = VideoJobStatus.GENERATING.value
        self.db.commit()

        logger.info("Started video production job %s → OpenMontage %s", job.id, result["project_id"])
        return {"started": True, "job_id": str(job.id), "project_id": result["project_id"]}

    def approve_job(self, job_id: UUID) -> dict[str, Any]:
        """Approve a job that is awaiting approval."""
        job = self.get_job(job_id)
        if job is None:
            return {"error": "Job not found"}
        if job.status != VideoJobStatus.AWAITING_APPROVAL.value:
            return {"error": f"Job is in state '{job.status}', cannot approve"}

        job.approved = True
        self.db.commit()
        logger.info("Approved video production job %s", job.id)
        return {"approved": True, "job_id": str(job.id)}

    def cancel_job(self, job_id: UUID) -> dict[str, Any]:
        """Cancel a running/queued job."""
        job = self.get_job(job_id)
        if job is None:
            return {"error": "Job not found"}
        if job.status in (VideoJobStatus.COMPLETED.value, VideoJobStatus.CANCELLED.value):
            return {"error": f"Job is in state '{job.status}', cannot cancel"}

        # Cancel the OpenMontage production if it has a project
        if job.project_id_openmontage and job.output_video_path is None:
            self.adapter.cancel_production(
                project_path=str(
                    Path(self.config.projects_path) / job.project_id_openmontage
                )
                if self.config.projects_path
                else ""
            )

        job.status = VideoJobStatus.CANCELLED.value
        job.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info("Cancelled video production job %s", job.id)
        return {"cancelled": True, "job_id": str(job.id)}

    def retry_job(self, job_id: UUID) -> dict[str, Any]:
        """Retry a failed job by resetting it to queued."""
        job = self.get_job(job_id)
        if job is None:
            return {"error": "Job not found"}
        if job.status != VideoJobStatus.FAILED.value:
            return {"error": f"Job is in state '{job.status}', cannot retry"}

        job.status = VideoJobStatus.QUEUED.value
        job.error_message = None
        job.error_stage = None
        job.current_stage = None
        job.progress_percent = 0
        self.db.commit()
        logger.info("Retried video production job %s", job.id)
        return {"retried": True, "job_id": str(job.id)}

    def poll_status(self, job_id: UUID) -> dict[str, Any]:
        """Poll the OpenMontage status and update the job record."""
        job = self.get_job(job_id)
        if job is None:
            return {"error": "Job not found"}
        if not job.project_id_openmontage or not self.config.projects_path:
            return {"status": job.status, "stage": job.current_stage}

        from pathlib import Path

        project_path = str(Path(self.config.projects_path) / job.project_id_openmontage)
        om_status = self.adapter.check_status(job.project_id_openmontage, project_path)

        # Map OpenMontage status to GoalOS status
        om_status_val = om_status.get("status", "")
        if om_status_val == "completed":
            job.status = VideoJobStatus.REVIEWING.value
            job.progress_percent = 90
        elif om_status_val == "failed":
            job.status = VideoJobStatus.FAILED.value
            job.error_message = om_status.get("error", "Production failed")
        elif om_status_val in ("generating", "rendering"):
            job.status = VideoJobStatus.GENERATING.value
            job.current_stage = om_status.get("stage", job.current_stage)

        # Collect artifacts if available
        if om_status.get("output_video"):
            job.output_video_path = om_status["output_video"]
            validation = self.adapter.validate_output(project_path)
            if validation.get("valid"):
                job.status = VideoJobStatus.COMPLETED.value
                job.duration_actual = validation.get("duration")
                job.resolution = validation.get("resolution")
                job.output_metadata = validation
                job.completed_at = datetime.now(timezone.utc)
                job.progress_percent = 100
            else:
                job.status = VideoJobStatus.FAILED.value
                job.error_message = f"Output validation failed: {validation.get('error')}"

        self.db.commit()
        return {"status": job.status, "stage": job.current_stage, "progress": job.progress_percent}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_available_pipelines(self) -> list[VideoPipelineInfo]:
        """Return available video pipelines."""
        pipelines = []
        for pid, display_name in PIPELINE_DISPLAY_NAMES.items():
            pipelines.append(
                VideoPipelineInfo(
                    name=pid,
                    display_name=display_name,
                    description={
                        "auto": "Automatically select the best pipeline",
                        "animated-explainer": "AI-generated animated explainer",
                        "talking-head": "Presenter-led video with footage",
                        "cinematic": "Cinematic edit with footage and music",
                        "clip-factory": "Extract short-form clips from source",
                        "podcast-repurpose": "Turn podcast into video",
                        "animation": "Full animation production",
                        "character-animation": "Character-driven animation",
                        "hybrid": "Combine source footage with AI-generated support",
                        "avatar-spokesperson": "AI avatar presenter",
                        "localization-dub": "Localize and dub video content",
                        "screen-demo": "Screen recording with narration",
                    }.get(pid, ""),
                    openmontage_pipeline=pid,
                )
            )
        return pipelines

    def get_provider_status(self) -> dict[str, Any]:
        """Return OpenMontage configuration and capability status."""
        return {
            "provider": "openmontage",
            "configured": self.adapter.is_configured,
            "installation_path": self.config.installation_path or None,
            "projects_path": self.config.projects_path or None,
            "default_pipeline": self.config.default_pipeline,
            "available_pipelines": len(PIPELINE_DISPLAY_NAMES) - 1,  # exclude 'auto'
            "openmontage_required": [
                "GOALOS_OPENMONTAGE_PATH",
                "GOALOS_OPENMONTAGE_PROJECTS",
            ],
        }


# Lazy import for Path to avoid circular imports
from pathlib import Path  # noqa: E402
