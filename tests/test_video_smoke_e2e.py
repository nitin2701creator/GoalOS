"""Real end-to-end smoke test for OpenMontage video production.

Proves the COMPLETE GoalOS lifecycle:
  API request → job → adapter → pipeline runner → actual ffmpeg render →
  real MP4 artifact → ffprobe validation → COMPLETED status

No mocking.  Real file I/O.  Real ffmpeg execution.  Real ffprobe validation.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import shutil
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.services.video_service import VideoProductionService
from app.schemas.video_production import VideoProductionRequest


@pytest.fixture()
def _om_env(monkeypatch, tmp_path):
    """Point OpenMontage at the real source tree and a temp projects dir."""
    om_root = str(Path("external/video/openmontage").resolve())
    projects_dir = str(tmp_path / "om_projects")
    Path(projects_dir).mkdir()
    monkeypatch.setenv("GOALOS_OPENMONTAGE_PATH", om_root)
    monkeypatch.setenv("GOALOS_OPENMONTAGE_PROJECTS", projects_dir)
    return om_root, projects_dir


@pytest.fixture()
def _db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _ffprobe(path: Path) -> dict:
    """Run ffprobe and return parsed JSON."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, f"ffprobe failed: {result.stderr}"
    return json.loads(result.stdout)


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5, check=True,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_real_e2e_video_production(_om_env, _db):
    """Full lifecycle: create job → start → render → validate artifact."""

    om_root, projects_dir = _om_env

    # --- 1. Create job through the service ---
    service = VideoProductionService(_db)
    req = VideoProductionRequest(
        prompt="Create a 5-second test video for GoalOS integration proof",
        duration_seconds=5,
        aspect_ratio="16:9",
        pipeline="animated-explainer",
        requires_approval=False,
    )
    job = service.create_job(req, requestor="smoke-test")
    assert job.status == "queued", f"Expected queued, got {job.status}"

    # --- 2. Verify adapter is configured ---
    assert service.adapter.is_configured, "Adapter not configured"
    assert service.config.installation_path, "No OM path"

    # --- 3. Start production (real pipeline execution) ---
    result = service.start_job(job.id)
    assert "error" not in result, f"start_job failed: {result}"
    assert result.get("started"), "Production did not start"

    # --- 5. Refresh and check job status ---
    _db.refresh(job)
    assert job.status == "completed", f"Expected completed, got {job.status}"
    assert job.output_video_path, "No output_video_path"

    # --- 6. Verify the artifact is a real video ---
    video_path = Path(job.output_video_path)
    assert video_path.exists(), f"Video file does not exist: {video_path}"
    assert video_path.stat().st_size > 0, "Video file is empty"
    assert video_path.suffix == ".mp4", f"Expected .mp4, got {video_path.suffix}"

    # --- 7. ffprobe validation ---
    probe = _ffprobe(video_path)
    fmt = probe.get("format", {})
    streams = probe.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})

    assert fmt.get("format_name") in ("mov,mp4,m4a,3gp,3g2,mj2", "mp4"), \
        f"Unexpected format: {fmt.get('format_name')}"
    assert float(fmt.get("duration", 0)) > 0, "Duration is zero"
    assert int(video_stream.get("width", 0)) > 0, "Width is zero"
    assert int(video_stream.get("height", 0)) > 0, "Height is zero"

    # --- 8. Verify the OpenMontage project directory was created ---
    project_id = job.project_id_openmontage
    assert project_id, "No project_id_openmontage"
    project_dir = Path(projects_dir) / project_id
    assert project_dir.exists(), f"Project dir not found: {project_dir}"
    assert (project_dir / "brief.json").exists(), "No brief.json"
    assert (project_dir / "state.json").exists(), "No state.json"

    final_state = json.loads((project_dir / "state.json").read_text())
    assert final_state["status"] == "completed"

    # --- 9. Verify output artifacts ---
    output_dir = project_dir / "output"
    assert output_dir.exists(), "No output/ directory"
    assert len(list(output_dir.glob("*.mp4"))) > 0, "No .mp4 in output/"
    assert len(list(output_dir.glob("*.png"))) > 0, "No thumbnail in output/"

    # --- 10. Summary ---
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    duration = float(fmt.get("duration", 0))
    size = video_path.stat().st_size

    print(f"\n{'='*60}")
    print(f"REAL VIDEO PRODUCED")
    print(f"  Path:     {video_path}")
    print(f"  Size:     {size} bytes ({size/1024:.1f} KB)")
    print(f"  Format:   {fmt.get('format_name')}")
    print(f"  Duration: {duration:.2f}s")
    print(f"  Res:      {width}x{height}")
    print(f"  Codec:    {video_stream.get('codec_name')}")
    print(f"  Job:      {job.id} → {job.status}")
    print(f"{'='*60}")
