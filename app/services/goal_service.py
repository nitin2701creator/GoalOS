"""
Goal business service.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from app.db.models.goal import Goal
from app.repositories.goal_repository import GoalRepository
from app.schemas.goal import GoalCreateRequest, GoalUpdateRequest


class GoalService:
    """Business operations for permanent goals."""

    def __init__(self, repository: GoalRepository):
        self.repository = repository

    def create(self, request: GoalCreateRequest) -> Goal:
        return self.repository.create(request)

    def get(self, goal_id: uuid.UUID) -> Goal | None:
        return self.repository.get(goal_id)

    def list(self) -> Sequence[Goal]:
        return self.repository.list()

    def update(self, goal_id: uuid.UUID, request: GoalUpdateRequest) -> Goal | None:
        goal = self.repository.get(goal_id)
        if goal is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return goal

        return self.repository.update(goal, updates)

    def delete(self, goal_id: uuid.UUID) -> bool:
        goal = self.repository.get(goal_id)
        if goal is None:
            return False

        self.repository.delete(goal)
        return True
