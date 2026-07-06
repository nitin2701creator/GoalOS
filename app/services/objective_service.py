"""
Objective business service.
"""

from __future__ import annotations

import uuid

from app.db.models.objective import Objective
from app.repositories.goal_repository import GoalRepository
from app.repositories.objective_repository import ObjectiveRepository
from app.schemas.objective import ObjectiveCreateRequest, ObjectiveResponse, ObjectiveUpdateRequest


class ObjectiveService:
    """Business operations for objectives."""

    def __init__(self, goal_repository: GoalRepository, repository: ObjectiveRepository):
        self.goal_repository = goal_repository
        self.repository = repository

    def _to_response(self, objective: Objective) -> ObjectiveResponse:
        return ObjectiveResponse.model_validate(objective)

    def create(self, request: ObjectiveCreateRequest) -> ObjectiveResponse | None:
        if self.goal_repository.get(request.goal_id) is None:
            return None

        objective = self.repository.create(request)
        return self._to_response(objective)

    def get(self, objective_id: uuid.UUID) -> ObjectiveResponse | None:
        objective = self.repository.get(objective_id)
        if objective is None:
            return None
        return self._to_response(objective)

    def list(self) -> list[ObjectiveResponse]:
        return [self._to_response(objective) for objective in self.repository.list()]

    def list_by_goal(self, goal_id: uuid.UUID) -> list[ObjectiveResponse] | None:
        if self.goal_repository.get(goal_id) is None:
            return None
        return [self._to_response(objective) for objective in self.repository.list_by_goal(goal_id)]

    def update(self, objective_id: uuid.UUID, request: ObjectiveUpdateRequest) -> ObjectiveResponse | None:
        objective = self.repository.get(objective_id)
        if objective is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if "goal_id" in updates and updates["goal_id"] is None:
            updates.pop("goal_id")

        if not updates:
            return self._to_response(objective)

        if "goal_id" in updates and self.goal_repository.get(updates["goal_id"]) is None:
            return None

        if "updated_by" not in updates or updates["updated_by"] is None:
            updates["updated_by"] = "system"

        return self._to_response(self.repository.update(objective, updates))

    def delete(self, objective_id: uuid.UUID) -> bool:
        objective = self.repository.get(objective_id)
        if objective is None:
            return False

        self.repository.delete(objective)
        return True
