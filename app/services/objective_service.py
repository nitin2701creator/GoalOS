"""
Objective business service.
"""

from __future__ import annotations

import uuid

from app.db.models.objective import Objective
from app.repositories.objective_repository import ObjectiveRepository
from app.schemas.objective import (
    ObjectiveCreateRequest,
    ObjectiveResponse,
    ObjectiveUpdateRequest,
)


class ObjectiveService:
    """Business operations for goal objectives."""

    def __init__(self, repository: ObjectiveRepository):
        self.repository = repository

    def _to_response(self, objective: Objective) -> ObjectiveResponse:
        return ObjectiveResponse.model_validate(objective)

    def create(self, request: ObjectiveCreateRequest) -> ObjectiveResponse:
        return self._to_response(self.repository.create(request))

    def get(self, objective_id: uuid.UUID) -> ObjectiveResponse | None:
        objective = self.repository.get(objective_id)
        if objective is None:
            return None
        return self._to_response(objective)

    def list(self) -> list[ObjectiveResponse]:
        return [self._to_response(objective) for objective in self.repository.list()]

    def update(self, objective_id: uuid.UUID, request: ObjectiveUpdateRequest) -> ObjectiveResponse | None:
        objective = self.repository.get(objective_id)
        if objective is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(objective)

        return self._to_response(self.repository.update(objective, updates))

    def delete(self, objective_id: uuid.UUID) -> bool:
        objective = self.repository.get(objective_id)
        if objective is None:
            return False

        self.repository.delete(objective)
        return True
