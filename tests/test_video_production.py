"""Tests for the GoalOS video production capability.

Covers: adapter initialization, pipeline mapping, job creation,
lifecycle transitions, artifact validation, error handling, and
the video production API.
"""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.db.models.video_production import VideoJobStatus, VideoProduction
from app.integrations.video.openmontage_adapter import (
    OpenMontageAdapter,
    OpenMontageConfig,
    PIPELINE_MAP,
    PIPELINE_DISPLAY_NAMES,
)
from app.schemas.video_production import (
    VideoPipelineInfo,
    VideoProductionRequest,
    VideoProductionResponse,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Provide an isolated database session per test."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'video_test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def api(tmp_path, monkeypatch):
    """Provide a FastAPI TestClient with isolated DB."""
    from app.main import app
    monkeypatch.delenv("GOALOS_OPENMONTAGE_PATH", raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'video_api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# Pipeline Mapping
# ---------------------------------------------------------------------------

class TestPipelineMapping:
    def test_all_display_names_have_descriptions(self):
        for pid, name in PIPELINE_DISPLAY_NAMES.items():
            assert isinstance(name, str)
            assert len(name) > 0

    def test_pipeline_map_covers_display_names(self):
        for pid in PIPELINE_DISPLAY_NAMES:
            if pid == "auto":
                continue
            assert pid in PIPELINE_MAP.values() or pid in PIPELINE_MAP, (
                f"Pipeline '{pid}' not in PIPELINE_MAP"
            )

    def test_resolve_auto_defaults_to_explainer(self):
        config = OpenMontageConfig(default_pipeline="animated-explainer")
        adapter = OpenMontageAdapter(config)
        assert adapter.resolve_pipeline("auto") == "animated-explainer"

    def test_resolve_known_pipeline(self):
        config = OpenMontageConfig(default_pipeline="animated-explainer")
        adapter = OpenMontageAdapter(config)
        assert adapter.resolve_pipeline("cinematic") == "cinematic"

    def test_resolve_alias(self):
        config = OpenMontageConfig(default_pipeline="animated-explainer")
        adapter = OpenMontageAdapter(config)
        assert adapter.resolve_pipeline("explainer") == "animated-explainer"
        assert adapter.resolve_pipeline("social-short") == "clip-factory"
        assert adapter.resolve_pipeline("podcast-clip") == "podcast-repurpose"

    def test_resolve_unknown_falls_back(self):
        config = OpenMontageConfig(default_pipeline="animated-explainer")
        adapter = OpenMontageAdapter(config)
        result = adapter.resolve_pipeline("totally-fake-pipeline")
        assert result == "animated-explainer"


# ---------------------------------------------------------------------------
# OpenMontage Adapter
# ---------------------------------------------------------------------------

class TestOpenMontageAdapter:
    def test_not_configured_when_no_path(self):
        adapter = OpenMontageAdapter(OpenMontageConfig(installation_path=""))
        assert not adapter.is_configured

    def test_not_configured_when_path_missing(self):
        adapter = OpenMontageAdapter(
            OpenMontageConfig(installation_path="/nonexistent/path")
        )
        assert not adapter.is_configured

    def test_configured_when_path_exists(self, tmp_path):
        adapter = OpenMontageAdapter(
            OpenMontageConfig(installation_path=str(tmp_path))
        )
        assert adapter.is_configured

    def test_create_project_not_configured(self):
        adapter = OpenMontageAdapter(OpenMontageConfig(installation_path=""))
        result = adapter.create_project(prompt="Test video")
        assert "error" in result
        assert result["configured"] is False

    def test_create_project_success(self, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        adapter = OpenMontageAdapter(
            OpenMontageConfig(
                installation_path=str(tmp_path),
                projects_path=str(projects_dir),
            )
        )
        result = adapter.create_project(
            prompt="Create a 30-second product demo",
            pipeline="cinematic",
            duration_seconds=30,
        )
        assert result["configured"] is True
        assert "project_id" in result
        assert result["pipeline"] == "cinematic"

        # Verify project files were created
        project_dir = Path(result["project_path"])
        assert project_dir.exists()
        assert (project_dir / "brief.json").exists()
        assert (project_dir / "state.json").exists()

        # Verify brief content
        brief = json.loads((project_dir / "brief.json").read_text())
        assert brief["prompt"] == "Create a 30-second product demo"
        assert brief["pipeline"] == "cinematic"

    def test_check_status_no_state(self, tmp_path):
        adapter = OpenMontageAdapter(OpenMontageConfig(installation_path=str(tmp_path)))
        result = adapter.check_status("fake-id", str(tmp_path / "nonexistent"))
        assert result["status"] == "unknown"

    def test_cancel_production(self, tmp_path):
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        adapter = OpenMontageAdapter(
            OpenMontageConfig(
                installation_path=str(tmp_path),
                projects_path=str(projects_dir),
            )
        )
        # Create a project first
        result = adapter.create_project(prompt="Test cancel")
        project_path = result["project_path"]

        # Cancel it
        cancel_result = adapter.cancel_production(project_path)
        assert cancel_result["cancelled"] is True

        # Verify state was updated
        state = json.loads((Path(project_path) / "state.json").read_text())
        assert state["status"] == "cancelled"

    def test_validate_output_no_output(self, tmp_path):
        adapter = OpenMontageAdapter(OpenMontageConfig(installation_path=str(tmp_path)))
        result = adapter.validate_output(str(tmp_path / "nonexistent"))
        assert result["valid"] is False

    def test_get_available_pipelines(self, tmp_path):
        adapter = OpenMontageAdapter(OpenMontageConfig(installation_path=str(tmp_path)))
        pipelines = adapter.get_available_pipelines()
        assert len(pipelines) > 0
        # auto should not be in the list
        names = [p["id"] for p in pipelines]
        assert "auto" not in names
        assert "animated-explainer" in names
        assert "cinematic" in names


# ---------------------------------------------------------------------------
# Video Production Request Schema
# ---------------------------------------------------------------------------

class TestVideoProductionRequest:
    def test_minimal_request(self):
        req = VideoProductionRequest(prompt="Make a video about cats")
        assert req.prompt == "Make a video about cats"
        assert req.duration_seconds is None
        assert req.aspect_ratio == "16:9"
        assert req.language == "en"
        assert req.pipeline == "auto"
        assert req.provider == "openmontage"

    def test_full_request(self):
        req = VideoProductionRequest(
            prompt="Create a 60-second product demo",
            duration_seconds=60,
            aspect_ratio="9:16",
            style="cinematic",
            audience="developers",
            language="en",
            voice="professional",
            music=True,
            captions=True,
            pipeline="animated-explainer",
        )
        assert req.duration_seconds == 60
        assert req.aspect_ratio == "9:16"
        assert req.style == "cinematic"
        assert req.pipeline == "animated-explainer"

    def test_empty_prompt_rejected(self):
        with pytest.raises(Exception):
            VideoProductionRequest(prompt="")

    def test_duration_bounds(self):
        req = VideoProductionRequest(prompt="Test", duration_seconds=5)
        assert req.duration_seconds == 5

        req2 = VideoProductionRequest(prompt="Test", duration_seconds=600)
        assert req2.duration_seconds == 600


# ---------------------------------------------------------------------------
# Video Production Service (with mocked adapter)
# ---------------------------------------------------------------------------

class TestVideoProductionService:
    def test_create_job(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        req = VideoProductionRequest(prompt="Test video production")
        job = service.create_job(req, requestor="test-user")
        assert job.id is not None
        assert job.status == VideoJobStatus.QUEUED.value
        assert job.prompt == "Test video production"
        assert job.requestor == "test-user"

    def test_get_job(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        req = VideoProductionRequest(prompt="Find me")
        job = service.create_job(req)
        found = service.get_job(job.id)
        assert found is not None
        assert found.id == job.id

    def test_get_nonexistent_job(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        found = service.get_job(uuid4())
        assert found is None

    def test_list_jobs(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        for i in range(3):
            service.create_job(VideoProductionRequest(prompt=f"Video {i}"))
        jobs = service.list_jobs()
        assert len(jobs) == 3

    def test_cancel_job(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        job = service.create_job(VideoProductionRequest(prompt="Cancel me"))
        result = service.cancel_job(job.id)
        assert result["cancelled"] is True
        refreshed = service.get_job(job.id)
        assert refreshed.status == VideoJobStatus.CANCELLED.value

    def test_cancel_completed_job_fails(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        job = service.create_job(VideoProductionRequest(prompt="Already done"))
        job.status = VideoJobStatus.COMPLETED.value
        db.commit()
        result = service.cancel_job(job.id)
        assert "error" in result

    def test_retry_failed_job(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        job = service.create_job(VideoProductionRequest(prompt="Retry me"))
        job.status = VideoJobStatus.FAILED.value
        job.error_message = "Something went wrong"
        db.commit()
        result = service.retry_job(job.id)
        assert result["retried"] is True
        refreshed = service.get_job(job.id)
        assert refreshed.status == VideoJobStatus.QUEUED.value
        assert refreshed.error_message is None

    def test_approve_job(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        job = service.create_job(VideoProductionRequest(prompt="Approve me"))
        job.status = VideoJobStatus.AWAITING_APPROVAL.value
        db.commit()
        result = service.approve_job(job.id)
        assert result["approved"] is True
        refreshed = service.get_job(job.id)
        assert refreshed.approved is True

    def test_start_job_not_approved_fails(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        job = service.create_job(VideoProductionRequest(
            prompt="Not approved", requires_approval=True
        ))
        job.status = VideoJobStatus.AWAITING_APPROVAL.value
        db.commit()
        result = service.start_job(job.id)
        assert "error" in result

    def test_start_job_unconfigured_fails(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        req = VideoProductionRequest(prompt="No OM installed", requires_approval=False)
        job = service.create_job(req)
        job.approved = True
        db.commit()
        result = service.start_job(job.id)
        assert "error" in result

    def test_get_pipelines(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        pipelines = service.get_available_pipelines()
        assert len(pipelines) > 0
        assert any(p.name == "animated-explainer" for p in pipelines)

    def test_provider_status(self, db):
        from app.services.video_service import VideoProductionService
        service = VideoProductionService(db)
        status = service.get_provider_status()
        assert status["provider"] == "openmontage"
        assert "configured" in status


# ---------------------------------------------------------------------------
# Video Production API
# ---------------------------------------------------------------------------

class TestVideoProductionAPI:
    def test_list_pipelines(self, api):
        response = api.get("/api/v1/video/pipelines")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(p["name"] == "animated-explainer" for p in data)

    def test_provider_status(self, api):
        response = api.get("/api/v1/video/status")
        assert response.status_code == 200
        data = response.json()
        assert data["provider"] == "openmontage"

    def test_create_production(self, api):
        response = api.post(
            "/api/v1/video",
            json={"prompt": "Create a 30-second demo video"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["prompt"] == "Create a 30-second demo video"
        assert data["status"] == "queued"

    def test_list_productions(self, api):
        # Create one first
        api.post("/api/v1/video", json={"prompt": "List test"})
        response = api.get("/api/v1/video")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    def test_get_production(self, api):
        create_resp = api.post(
            "/api/v1/video", json={"prompt": "Get test"}
        )
        job_id = create_resp.json()["id"]
        response = api.get(f"/api/v1/video/{job_id}")
        assert response.status_code == 200
        assert response.json()["prompt"] == "Get test"

    def test_get_nonexistent_production(self, api):
        fake_id = str(uuid4())
        response = api.get(f"/api/v1/video/{fake_id}")
        assert response.status_code == 404

    def test_cancel_production(self, api):
        create_resp = api.post(
            "/api/v1/video", json={"prompt": "Cancel test"}
        )
        job_id = create_resp.json()["id"]
        response = api.post(f"/api/v1/video/{job_id}/cancel")
        assert response.status_code == 200
        assert response.json()["cancelled"] is True

    def test_empty_prompt_rejected(self, api):
        response = api.post("/api/v1/video", json={"prompt": ""})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Pipeline Runner — REAL execution test (produces actual MP4)
# ---------------------------------------------------------------------------

class TestPipelineRunnerEndToEnd:
    """Proves the pipeline runner actually produces a video artifact."""

    def test_run_pipeline_produces_mp4(self, tmp_path):
        """The pipeline runner creates a real MP4 via ffmpeg fallback."""
        import subprocess

        # Check ffmpeg is available
        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pytest.skip("ffmpeg not available")

        from app.integrations.video.pipeline_runner import run_pipeline

        # Create a project directory with a brief
        project_dir = tmp_path / "test-project"
        project_dir.mkdir()
        (project_dir / "brief.json").write_text(json.dumps({
            "prompt": "Create a 5-second test video",
            "pipeline": "animated-explainer",
            "duration_seconds": 5,
            "aspect_ratio": "16:9",
            "language": "en",
        }))
        (project_dir / "state.json").write_text(json.dumps({
            "project_id": "test-001",
            "pipeline": "animated-explainer",
            "status": "queued",
        }))

        # Run the pipeline (no OM root needed — ffmpeg fallback)
        final_state = run_pipeline(
            project_dir=project_dir,
            om_root=tmp_path,  # no real OM installation
            pipeline_name="animated-explainer",
        )

        # Verify the state shows completion
        assert final_state["status"] == "completed"

        # Verify an MP4 was actually produced
        output_dir = project_dir / "output"
        assert output_dir.exists(), "output/ directory not created"
        video_files = list(output_dir.glob("*.mp4"))
        assert len(video_files) > 0, "No .mp4 file produced"

        video_path = video_files[0]
        assert video_path.stat().st_size > 0, "MP4 is empty"

        # Verify the MP4 is a valid video file using ffprobe
        probe_result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        assert probe_result.returncode == 0, f"ffprobe failed: {probe_result.stderr}"
        probe = json.loads(probe_result.stdout)
        assert "format" in probe, "No format info in ffprobe output"
        assert probe["format"]["format_name"] in ("mov,mp4,m4a,3gp,3g2,mj2", "mp4")

        # Verify a thumbnail was produced
        thumb_files = list(output_dir.glob("*.png"))
        assert len(thumb_files) > 0, "No thumbnail produced"

        # Verify stage results artifact exists
        artifacts_dir = project_dir / "artifacts"
        assert artifacts_dir.exists()
        stage_results = json.loads((artifacts_dir / "stage_results.json").read_text())
        assert len(stage_results) > 0
        assert any(r.get("status") == "completed" for r in stage_results)

    def test_pipeline_runner_state_transitions(self, tmp_path):
        """The pipeline runner writes correct state transitions."""
        import subprocess

        try:
            subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True, timeout=5, check=True,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pytest.skip("ffmpeg not available")

        from app.integrations.video.pipeline_runner import run_pipeline

        project_dir = tmp_path / "transition-test"
        project_dir.mkdir()
        (project_dir / "brief.json").write_text(json.dumps({
            "prompt": "State transition test",
            "pipeline": "animated-explainer",
            "duration_seconds": 3,
        }))
        (project_dir / "state.json").write_text(json.dumps({
            "project_id": "trans-001",
            "status": "queued",
        }))

        final_state = run_pipeline(
            project_dir=project_dir,
            om_root=tmp_path,
            pipeline_name="animated-explainer",
        )

        # State should have passed through generating → completed
        assert final_state["status"] == "completed"
        assert final_state.get("output_video") is not None
        assert "completed_at" in final_state

    def test_cancelled_state_not_overwritten(self, tmp_path):
        """If state is cancelled before pipeline finishes, it stays cancelled."""
        from app.integrations.video.pipeline_runner import _update_state, _read_state

        project_dir = tmp_path / "cancel-test"
        project_dir.mkdir()
        (project_dir / "brief.json").write_text(json.dumps({
            "prompt": "Cancel test",
            "pipeline": "animated-explainer",
        }))
        (project_dir / "state.json").write_text(json.dumps({
            "project_id": "cancel-001",
            "status": "generating",
        }))

        # Simulate cancellation
        _update_state(project_dir, status="cancelled")
        state = _read_state(project_dir)
        assert state["status"] == "cancelled"
