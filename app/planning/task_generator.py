"""Deterministic task planning logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class TaskGenerator:
    """Generates tasks from projects."""

    def generate(self, projects: list[dict]) -> list[dict]:
        tasks = []
        now = datetime.now(timezone.utc)
        for project_index, project in enumerate(projects, start=1):
            for step in range(1, 4):
                task_id = uuid.uuid5(uuid.NAMESPACE_URL, f"task:{project['id']}:{step}")
                tasks.append(
                    {
                        "id": task_id,
                        "project_id": project["id"],
                        "title": f"Task {project_index}.{step}: {project['title']} step {step}",
                        "description": f"Complete phase {step} of project '{project['title']}'.",
                        "assigned_agent": None,
                        "status": "Draft",
                        "priority": "Medium",
                        "workflow_id": None,
                        "sequence_number": step,
                        "depends_on_task_id": None,
                        "execution_order": step,
                        "estimated_hours": 8.0,
                        "actual_hours": None,
                        "due_date": None,
                        "result": None,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
        return tasks
