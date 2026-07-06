"""
Goal business service.
"""

from __future__ import annotations

import uuid

from app.db.models.goal import Goal, GoalStatus
from app.repositories.goal_repository import GoalRepository
from app.schemas.goal import GoalCreateRequest, GoalResponse, GoalSummaryResponse, GoalUpdateRequest
from app.schemas.objective import ObjectiveResponse


class GoalService:
    """Business operations for permanent goals."""

    def __init__(self, repository: GoalRepository):
        self.repository = repository

    def _metrics(self, goal: Goal) -> tuple[int, int, int]:
        objective_count = len(goal.objectives)
        completed_objective_count = sum(
            1 for objective in goal.objectives if objective.status == GoalStatus.COMPLETED
        )
        if objective_count == 0:
            return 0, 0, 0
        progress_percentage = round((completed_objective_count / objective_count) * 100)
        return objective_count, completed_objective_count, progress_percentage

    def _to_response(self, goal: Goal) -> GoalResponse:
        objective_count, completed_objective_count, progress_percentage = self._metrics(goal)
        return GoalResponse(
            id=goal.id,
            company_id=goal.company_id,
            title=goal.title,
            description=goal.description,
            executive_owner=goal.executive_owner,
            department=goal.department,
            priority=goal.priority,
            status=goal.status,
            target_date=goal.target_date,
            objective_count=objective_count,
            completed_objective_count=completed_objective_count,
            progress_percentage=progress_percentage,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )

    def _to_objectives(self, goal: Goal) -> list[ObjectiveResponse]:
        return [ObjectiveResponse.model_validate(objective) for objective in goal.objectives]

    def create(self, request: GoalCreateRequest) -> GoalResponse:
        return self._to_response(self.repository.create(request))

    def get(self, goal_id: uuid.UUID) -> GoalResponse | None:
        goal = self.repository.get(goal_id)
        if goal is None:
            return None
        return self._to_response(goal)

    def list(self) -> list[GoalResponse]:
        return [self._to_response(goal) for goal in self.repository.list()]

    def update(self, goal_id: uuid.UUID, request: GoalUpdateRequest) -> GoalResponse | None:
        goal = self.repository.get(goal_id)
        if goal is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(goal)

        return self._to_response(self.repository.update(goal, updates))

    def delete(self, goal_id: uuid.UUID) -> bool:
        goal = self.repository.get(goal_id)
        if goal is None:
            return False

        self.repository.delete(goal)
        return True

    def summary(self, goal_id: uuid.UUID) -> GoalSummaryResponse | None:
        goal = self.repository.get(goal_id)
        if goal is None:
            return None

        objective_count, completed_objective_count, progress_percentage = self._metrics(goal)
        return GoalSummaryResponse(
            goal=self._to_response(goal),
            objectives=self._to_objectives(goal),
            objective_count=objective_count,
            completed_objective_count=completed_objective_count,
            progress_percentage=progress_percentage,
        )

    def objectives(self, goal_id: uuid.UUID) -> list[ObjectiveResponse] | None:
        goal = self.repository.get(goal_id)
        if goal is None:
            return None
        return self._to_objectives(goal)
