"""OpenMontage video production integration provider.

OpenMontage is an open-source, agentic video production system.
GoalOS integrates with it as a subprocess-based video engine.

Environment variables:
    GOALOS_OPENMONTAGE_PATH       — Path to the OpenMontage installation
    GOALOS_OPENMONTAGE_PROJECTS   — Path where projects are stored
    GOALOS_OPENMONTAGE_DEFAULT_PIPELINE — Default pipeline
"""

from __future__ import annotations

import os
from pathlib import Path

from integrations_manager.app.providers.base import (
    BaseProvider,
    IntegrationInfo,
    OAuthConfig,
    TestResult,
)


class OpenMontageProvider(BaseProvider):
    """OpenMontage video production integration provider."""

    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="openmontage",
            name="Video Production / OpenMontage",
            description="AI-powered video production engine with 12 pipelines and 100+ tools",
            icon="🎬",
            auth_type="api_key",
            credential_fields=[
                {
                    "key": "installation_path",
                    "label": "OpenMontage Installation Path",
                    "type": "url",
                    "required": True,
                    "description": "Path to the OpenMontage repository (e.g. /opt/OpenMontage)",
                },
                {
                    "key": "projects_path",
                    "label": "Projects Directory",
                    "type": "url",
                    "required": True,
                    "description": "Directory where OpenMontage stores project files and outputs",
                },
                {
                    "key": "default_pipeline",
                    "label": "Default Pipeline",
                    "type": "text",
                    "required": False,
                    "description": "Default pipeline when auto-selecting (animated-explainer, cinematic, etc.)",
                },
            ],
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return None  # OpenMontage uses local installation, not OAuth

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        installation_path = credentials.get("installation_path", "").strip()
        projects_path = credentials.get("projects_path", "").strip()

        if not installation_path:
            return TestResult(success=False, message="Installation path is required")

        # Check if the installation path exists and looks like OpenMontage
        om_path = Path(installation_path)
        if not om_path.exists():
            return TestResult(
                success=False,
                message=f"Path does not exist: {installation_path}",
            )

        # Check for key OpenMontage files
        key_files = ["AGENT_GUIDE.md", "pipeline_defs", "tools"]
        found = []
        missing = []
        for f in key_files:
            if (om_path / f).exists():
                found.append(f)
            else:
                missing.append(f)

        if missing:
            return TestResult(
                success=False,
                message=f"Path exists but doesn't look like OpenMontage (missing: {', '.join(missing)})",
                details={"found": found, "missing": missing},
            )

        # Check projects directory if specified
        if projects_path:
            proj_path = Path(projects_path)
            if not proj_path.exists():
                try:
                    proj_path.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    return TestResult(
                        success=False,
                        message=f"Cannot create projects directory: {e}",
                    )

        # Check Python 3.10+ is available
        import sys
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"

        # Check FFmpeg
        import shutil
        ffmpeg_available = shutil.which("ffmpeg") is not None

        # Check Node.js
        import subprocess
        node_available = False
        try:
            result = subprocess.run(
                ["node", "--version"], capture_output=True, text=True, timeout=5,
            )
            node_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        return TestResult(
            success=True,
            message="OpenMontage installation verified",
            details={
                "installation_path": installation_path,
                "key_files_found": found,
                "python_version": python_version,
                "ffmpeg_available": ffmpeg_available,
                "node_available": node_available,
                "projects_path": projects_path or "not set",
            },
        )

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        installation_path = credentials.get("installation_path", "").strip()
        if not installation_path:
            return {"error": "Installation path not configured"}

        om_path = Path(installation_path)
        if not om_path.exists():
            return {"error": f"Path does not exist: {installation_path}"}

        # Count available pipelines
        pipeline_dir = om_path / "pipeline_defs"
        pipelines = []
        if pipeline_dir.exists():
            pipelines = [f.stem for f in pipeline_dir.glob("*.yaml")]

        # Count tools
        tools_dir = om_path / "tools"
        tool_count = 0
        if tools_dir.exists():
            tool_count = len(list(tools_dir.rglob("*.py"))) - 1  # exclude __init__.py

        return {
            "provider": "openmontage",
            "installation_path": installation_path,
            "pipelines_available": len(pipelines),
            "pipelines": sorted(pipelines),
            "tools_discovered": tool_count,
        }
