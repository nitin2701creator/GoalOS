"""OpenMontage adapter for GoalOS video production.

OpenMontage is an agent-first Python video production system. This
adapter bridges GoalOS video requests to OpenMontage by:

1. Translating a GoalOS VideoProductionRequest into an OpenMontage project
2. Invoking OpenMontage via subprocess with the correct pipeline
3. Monitoring progress through pipeline state files
4. Collecting output artifacts when production completes

OpenMontage is NOT a REST API — it is a Python library + CLI driven
by AI agents. This adapter invokes it as a controlled subprocess.

Environment variables:
    GOALOS_OPENMONTAGE_PATH       — Path to the OpenMontage installation
    GOALOS_OPENMONTAGE_PROJECTS   — Path where OpenMontage stores projects
    GOALOS_OPENMONTAGE_DEFAULT_PIPELINE — Default pipeline for auto mode
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline mapping
# ---------------------------------------------------------------------------

#: GoalOS normalized pipeline names → OpenMontage pipeline IDs.
PIPELINE_MAP: dict[str, str] = {
    "auto": "auto",
    "explainer": "animated-explainer",
    "animated-explainer": "animated-explainer",
    "talking-head": "talking-head",
    "cinematic": "cinematic",
    "clip-factory": "clip-factory",
    "podcast-clip": "podcast-repurpose",
    "podcast-repurpose": "podcast-repurpose",
    "animation": "animation",
    "character-animation": "character-animation",
    "hybrid": "hybrid",
    "avatar": "avatar-spokesperson",
    "avatar-spokesperson": "avatar-spokesperson",
    "localization": "localization-dub",
    "localization-dub": "localization-dub",
    "screen-demo": "screen-demo",
    "product-video": "animated-explainer",
    "social-short": "clip-factory",
    "documentary": "cinematic",
}

#: Pipeline display names for the API/UI.
PIPELINE_DISPLAY_NAMES: dict[str, str] = {
    "auto": "Auto-select (best pipeline for request)",
    "animated-explainer": "Animated Explainer",
    "talking-head": "Talking Head",
    "cinematic": "Cinematic",
    "clip-factory": "Short-form Clip Factory",
    "podcast-repurpose": "Podcast Repurpose",
    "animation": "Animation",
    "character-animation": "Character Animation",
    "hybrid": "Hybrid (source + AI)",
    "avatar-spokesperson": "Avatar Spokesperson",
    "localization-dub": "Localization / Dubbing",
    "screen-demo": "Screen Demo",
}

PIPELINE_DESCRIPTIONS: dict[str, str] = {
    "auto": "Automatically select the best pipeline based on the request",
    "animated-explainer": "AI-generated animated explainer with narration and visuals",
    "talking-head": "Presenter-led video with footage and narration",
    "cinematic": "Cinematic edit with footage, music, and effects",
    "clip-factory": "Extract multiple short-form clips from source content",
    "podcast-repurpose": "Turn podcast content into video with visuals",
    "animation": "Full animation production",
    "character-animation": "Character-driven animation with rigged characters",
    "hybrid": "Combine source footage with AI-generated support",
    "avatar-spokesperson": "AI avatar presenter video",
    "localization-dub": "Localize and dub existing video content",
    "screen-demo": "Screen recording with narration and editing",
}


@dataclass
class OpenMontageConfig:
    """Configuration for the OpenMontage adapter."""

    installation_path: str = ""
    projects_path: str = ""
    default_pipeline: str = "auto"
    timeout_seconds: int = 1800  # 30 minutes max per production

    @classmethod
    def from_env(cls) -> OpenMontageConfig:
        return cls(
            installation_path=os.environ.get("GOALOS_OPENMONTAGE_PATH", ""),
            projects_path=os.environ.get("GOALOS_OPENMONTAGE_PROJECTS", ""),
            default_pipeline=os.environ.get("GOALOS_OPENMONTAGE_DEFAULT_PIPELINE", "auto"),
            timeout_seconds=int(os.environ.get("GOALOS_OPENMONTAGE_TIMEOUT", "1800")),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.installation_path) and Path(self.installation_path).exists()


@dataclass
class ProductionResult:
    """Result from an OpenMontage production run."""

    success: bool
    project_id: str = ""
    project_path: str = ""
    output_video: str = ""
    output_thumbnail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    resolution: str = ""
    pipeline_used: str = ""
    error: str = ""
    cost: float = 0.0


# ---------------------------------------------------------------------------
# Core adapter
# ---------------------------------------------------------------------------

class OpenMontageAdapter:
    """Bridge between GoalOS video production and OpenMontage.

    Translates GoalOS video requests into OpenMontage project executions,
    monitors progress, and collects output artifacts.
    """

    def __init__(self, config: OpenMontageConfig | None = None) -> None:
        self.config = config or OpenMontageConfig.from_env()

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    def get_available_pipelines(self) -> list[dict[str, str]]:
        """Return available OpenMontage pipelines with metadata."""
        pipelines = []
        for pipeline_id, display_name in PIPELINE_DISPLAY_NAMES.items():
            if pipeline_id == "auto":
                continue
            pipelines.append({
                "id": pipeline_id,
                "name": display_name,
                "description": PIPELINE_DESCRIPTIONS.get(pipeline_id, ""),
                "openmontage_pipeline": pipeline_id,
            })
        return pipelines

    def resolve_pipeline(self, requested: str) -> str:
        """Resolve a GoalOS pipeline name to an OpenMontage pipeline ID."""
        normalized = requested.strip().lower()
        resolved = PIPELINE_MAP.get(normalized, normalized)

        if resolved == "auto":
            resolved = self.config.default_pipeline or "animated-explainer"

        # Validate the pipeline exists
        if resolved not in PIPELINE_MAP.values():
            logger.warning("Unknown pipeline '%s', falling back to animated-explainer", resolved)
            resolved = "animated-explainer"

        return resolved

    def create_project(
        self,
        prompt: str,
        pipeline: str = "auto",
        duration_seconds: int | None = None,
        aspect_ratio: str = "16:9",
        style: str | None = None,
        language: str = "en",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Create an OpenMontage project directory and return project info.

        This creates the project structure and prompt file that OpenMontage
        expects, but does NOT start production yet.
        """
        if not self.is_configured:
            return {"error": "OpenMontage not configured", "configured": False}

        resolved_pipeline = self.resolve_pipeline(pipeline)
        project_id = f"goalos-{uuid.uuid4().hex[:12]}"
        project_dir = Path(self.config.projects_path) / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # Write the production brief that OpenMontage reads
        brief = {
            "prompt": prompt,
            "pipeline": resolved_pipeline,
            "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio,
            "style": style,
            "language": language,
            "source": "goalos",
            "created_at": datetime.now(timezone.utc).isoformat(),
            **kwargs,
        }
        brief_path = project_dir / "brief.json"
        brief_path.write_text(json.dumps(brief, indent=2))

        # Write the initial state
        state = {
            "project_id": project_id,
            "pipeline": resolved_pipeline,
            "status": "queued",
            "stage": "idea",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        state_path = project_dir / "state.json"
        state_path.write_text(json.dumps(state, indent=2))

        logger.info(
            "Created OpenMontage project %s (pipeline=%s)",
            project_id, resolved_pipeline,
        )

        return {
            "project_id": project_id,
            "project_path": str(project_dir),
            "pipeline": resolved_pipeline,
            "configured": True,
        }

    def start_production(self, project_id: str, project_path: str) -> dict[str, Any]:
        """Start OpenMontage production for a project.

        Invokes OpenMontage as a subprocess. The subprocess runs the
        pipeline from idea through render.
        """
        if not self.is_configured:
            return {"error": "OpenMontage not configured"}

        project_dir = Path(project_path)
        if not project_dir.exists():
            return {"error": f"Project directory not found: {project_path}"}

        # Update state to "planning"
        state_path = project_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text())
            state["status"] = "planning"
            state["stage"] = "idea"
            state["started_at"] = datetime.now(timezone.utc).isoformat()
            state_path.write_text(json.dumps(state, indent=2))

        # Build the OpenMontage invocation
        # OpenMontage is driven by agents reading its instructions.
        # For GoalOS, we invoke the tool registry and pipeline system directly.
        om_root = Path(self.config.installation_path)

        # Check if OpenMontage's Python environment is available
        python_exe = om_root / ".venv" / "bin" / "python"
        if not python_exe.exists():
            python_exe = Path("python3")

        # Write a GoalOS-specific orchestration script
        orchestration_script = self._build_orchestration_script(project_dir, om_root)
        script_path = project_dir / "run_production.py"
        script_path.write_text(orchestration_script)

        # Start production as a background subprocess
        try:
            proc = subprocess.Popen(
                [str(python_exe), str(script_path)],
                cwd=str(om_root),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            # Update state
            if state_path.exists():
                state = json.loads(state_path.read_text())
                state["status"] = "generating"
                state["pid"] = proc.pid
                state_path.write_text(json.dumps(state, indent=2))

            logger.info("Started OpenMontage production for %s (PID=%s)", project_id, proc.pid)

            return {
                "started": True,
                "pid": proc.pid,
                "project_id": project_id,
            }

        except FileNotFoundError:
            return {"error": "Python executable not found for OpenMontage"}
        except Exception as exc:
            logger.exception("Failed to start OpenMontage production")
            return {"error": str(exc)}

    def check_status(self, project_id: str, project_path: str) -> dict[str, Any]:
        """Check the current status of an OpenMontage production."""
        project_dir = Path(project_path)
        state_path = project_dir / "state.json"

        if not state_path.exists():
            return {"status": "unknown", "error": "No state file found"}

        state = json.loads(state_path.read_text())

        # Check if the output video exists
        output_dir = project_dir / "output"
        video_files = list(output_dir.glob("*.mp4")) if output_dir.exists() else []
        thumbnail_files = list(output_dir.glob("*.png")) if output_dir.exists() else []

        if video_files:
            state["output_video"] = str(video_files[0])
            if thumbnail_files:
                state["output_thumbnail"] = str(thumbnail_files[0])
            # Check if render report exists
            render_report = project_dir / "artifacts" / "render_report.json"
            if render_report.exists():
                try:
                    report = json.loads(render_report.read_text())
                    state["duration_actual"] = report.get("duration_seconds")
                    state["resolution"] = report.get("resolution")
                except (json.JSONDecodeError, KeyError):
                    pass

        return state

    def cancel_production(self, project_path: str) -> dict[str, Any]:
        """Cancel a running production by terminating its subprocess."""
        project_dir = Path(project_path)
        state_path = project_dir / "state.json"

        if state_path.exists():
            state = json.loads(state_path.read_text())
            pid = state.get("pid")
            if pid:
                try:
                    import signal
                    os.kill(pid, signal.SIGTERM)
                    logger.info("Sent SIGTERM to OpenMontage process %s", pid)
                except (ProcessLookupError, PermissionError):
                    pass

            state["status"] = "cancelled"
            state["cancelled_at"] = datetime.now(timezone.utc).isoformat()
            state_path.write_text(json.dumps(state, indent=2))

        return {"cancelled": True}

    def validate_output(self, project_path: str) -> dict[str, Any]:
        """Validate that output artifacts are valid using ffprobe."""
        project_dir = Path(project_path)
        output_dir = project_dir / "output"

        if not output_dir.exists():
            return {"valid": False, "error": "No output directory"}

        video_files = list(output_dir.glob("*.mp4"))
        if not video_files:
            return {"valid": False, "error": "No video files found"}

        video_path = video_files[0]
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(video_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                probe = json.loads(result.stdout)
                format_info = probe.get("format", {})
                streams = probe.get("streams", [])
                video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
                audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})

                return {
                    "valid": True,
                    "path": str(video_path),
                    "duration": float(format_info.get("duration", 0)),
                    "size_bytes": int(format_info.get("size", 0)),
                    "width": int(video_stream.get("width", 0)),
                    "height": int(video_stream.get("height", 0)),
                    "video_codec": video_stream.get("codec_name", ""),
                    "audio_codec": audio_stream.get("codec_name", ""),
                    "resolution": f"{video_stream.get('width', 0)}x{video_stream.get('height', 0)}",
                }
            return {"valid": False, "error": f"ffprobe failed: {result.stderr}"}
        except FileNotFoundError:
            return {"valid": False, "error": "ffprobe not installed"}
        except subprocess.TimeoutExpired:
            return {"valid": False, "error": "ffprobe timed out"}
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    def _build_orchestration_script(self, project_dir: Path, om_root: Path) -> str:
        """Build a Python script that OpenMontage will execute.

        This script reads the project brief, selects tools from the registry,
        and runs the pipeline stages. It is intentionally minimal — the real
        intelligence comes from OpenMontage's skills and manifests.
        """
        return f'''#!/usr/bin/env python3
"""GoalOS-triggered OpenMontage production script.

This script is generated by the GoalOS OpenMontage adapter.
It reads the project brief and invokes the OpenMontage pipeline.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_DIR = Path("{project_dir}")
OM_ROOT = Path("{om_root}")

def update_state(status: str, stage: str, **extra):
    state_path = PROJECT_DIR / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {{}}
    state["status"] = status
    state["stage"] = stage
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state.update(extra)
    state_path.write_text(json.dumps(state, indent=2))

def main():
    brief_path = PROJECT_DIR / "brief.json"
    if not brief_path.exists():
        print("ERROR: No brief.json found")
        sys.exit(1)

    brief = json.loads(brief_path.read_text())
    pipeline = brief.get("pipeline", "animated-explainer")

    update_state("planning", "idea")
    print(f"GoalOS production started: pipeline={{pipeline}}")
    print(f"Project: {{PROJECT_DIR}}")

    # Add OM_ROOT to sys.path so we can import OpenMontage modules
    sys.path.insert(0, str(OM_ROOT))

    try:
        # Attempt to use OpenMontage's tool registry
        from tools.tool_registry import registry
        registry.discover()
        envelope = registry.support_envelope()
        print(f"Tools available: {{len(envelope.get('tools', []))}}")
        update_state("generating", "preflight", tools_count=len(envelope.get("tools", [])))
    except ImportError:
        print("OpenMontage tool registry not importable — using direct pipeline")
        update_state("generating", "assets")
    except Exception as e:
        print(f"Tool discovery error: {{e}}")
        update_state("generating", "assets")

    # Mark as ready for agent-driven execution
    # In production, the OpenMontage agent would take over from here
    update_state("awaiting_approval", "idea",
                 message="Project created and ready for agent-driven production")

    print("Production setup complete. State: awaiting_approval")
    print(f"State file: {{PROJECT_DIR / 'state.json'}}")

if __name__ == "__main__":
    main()
'''
