"""Deterministic objective planning logic."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


class ObjectiveGenerator:
    """Generates objectives from mission and goals."""

    def generate(self, vision: str, mission: str, goals: list[str]) -> list[dict]:
        if not goals:
            return []

        objectives = []
        now = datetime.now(timezone.utc)
        for index, goal in enumerate(goals, start=1):
            goal_id = uuid.uuid5(uuid.NAMESPACE_URL, goal)
            objective_id = uuid.uuid5(uuid.NAMESPACE_URL, f"objective:{goal}")
            objectives.append(
                {
                    "id": objective_id,
                    "goal_id": goal_id,
                    "title": f"Objective {index}: Align with {goal}",
                    "description": f"Establish measurable outcomes to support the business goal '{goal}'.",
                    "status": "Draft",
                    "created_at": now,
                    "updated_at": now,
                }
            )
        return objectives
