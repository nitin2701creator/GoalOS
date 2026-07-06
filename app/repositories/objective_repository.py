"""
Objective persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.objective import Objective
from app.schemas.objective import ObjectiveCreateRequest


class ObjectiveRepository:
    """Database access for objectives."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, objective_data: ObjectiveCreateRequest) -> Objective:
        objective = Objective(**objective_data.model_dump())
        self.db.add(objective)
        self.db.commit()
        self.db.refresh(objective)
        return objective

    def get(self, objective_id: uuid.UUID) -> Objective | None:
        return self.db.get(Objective, objective_id)

    def list(self) -> Sequence[Objective]:
        statement = select(Objective).order_by(Objective.created_at.desc())
        return self.db.scalars(statement).all()

    def list_by_goal(self, goal_id: uuid.UUID) -> Sequence[Objective]:
        statement = (
            select(Objective)
            .where(Objective.goal_id == goal_id)
            .order_by(Objective.created_at.desc())
        )
        return self.db.scalars(statement).all()

    def update(self, objective: Objective, updates: dict[str, Any]) -> Objective:
        for field, value in updates.items():
            setattr(objective, field, value)
        self.db.commit()
        self.db.refresh(objective)
        return objective

    def delete(self, objective: Objective) -> None:
        self.db.delete(objective)
        self.db.commit()
