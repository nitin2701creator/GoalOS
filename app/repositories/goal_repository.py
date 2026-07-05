"""
Goal persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.goal import Goal
from app.schemas.goal import GoalCreateRequest


class GoalRepository:
    """Database access for goals."""

    def __init__(self, db: Session):
        self.db = db

    def create(self, goal_data: GoalCreateRequest) -> Goal:
        goal = Goal(**goal_data.model_dump())
        self.db.add(goal)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def get(self, goal_id: uuid.UUID) -> Goal | None:
        return self.db.get(Goal, goal_id)

    def list(self) -> Sequence[Goal]:
        return self.db.scalars(select(Goal).order_by(Goal.created_at.desc())).all()

    def update(self, goal: Goal, updates: dict[str, Any]) -> Goal:
        for field, value in updates.items():
            setattr(goal, field, value)
        self.db.commit()
        self.db.refresh(goal)
        return goal

    def delete(self, goal: Goal) -> None:
        self.db.delete(goal)
        self.db.commit()
