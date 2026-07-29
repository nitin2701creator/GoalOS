"""Deterministic workflow planning logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class WorkflowGenerator:
    """Generates workflows from projects and tasks."""

    def generate(self, projects: list[dict], tasks: list[dict]) -> list[dict]:
        workflows = []
        now = datetime.now(timezone.utc)
        for project in projects:
            workflow_id = uuid.uuid5(uuid.NAMESPACE_URL, f"workflow:{project['id']}")
            workflows.append(
                {
                    "id": workflow_id,
                    "project_id": project["id"],
                    "name": f"Workflow for {project['title']}",
                    "status": "Pending",
                    "progress_percentage": 0,
                    "started_at": None,
                    "completed_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return workflows
