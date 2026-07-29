"""Deterministic project planning logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class ProjectGenerator:
    """Generates projects from objectives."""

    def generate(self, objectives: list[dict]) -> list[dict]:
        projects = []
        now = datetime.now(timezone.utc)
        for index, objective in enumerate(objectives, start=1):
            project_id = uuid.uuid5(uuid.NAMESPACE_URL, f"project:{objective['id']}")
            projects.append(
                {
                    "id": project_id,
                    "goal_id": objective["goal_id"],
                    "company_id": None,
                    "title": f"Project {index}: Deliver {objective['title']}",
                    "description": f"Plan and execute the work needed to achieve the objective '{objective['title']}'.",
                    "owner": "planning-team",
                    "department": "Strategy",
                    "priority": "Medium",
                    "status": "Draft",
                    "start_date": None,
                    "target_date": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return projects
