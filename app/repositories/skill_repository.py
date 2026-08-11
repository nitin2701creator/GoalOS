"""
Skill persistence repository.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models.skill import Skill


class SkillRepository:
    """Database access for persisted skill definitions."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> Skill:
        skill = Skill(**values)
        self.db.add(skill)
        try:
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ValueError(f"skill already exists: {values.get('name')}") from exc
        self.db.refresh(skill)
        return skill

    def get(self, skill_id: uuid.UUID) -> Skill | None:
        statement = select(Skill).where(Skill.id == skill_id)
        return self.db.scalars(statement).one_or_none()

    def get_by_name(self, name: str) -> Skill | None:
        statement = select(Skill).where(Skill.name == name)
        return self.db.scalars(statement).one_or_none()

    def list(self) -> Sequence[Skill]:
        statement = select(Skill).order_by(Skill.name.asc())
        return self.db.scalars(statement).all()

    def update(self, skill: Skill, updates: dict[str, Any]) -> Skill:
        for field, value in updates.items():
            setattr(skill, field, value)
        self.db.commit()
        self.db.refresh(skill)
        return skill

    def delete(self, skill: Skill) -> None:
        self.db.delete(skill)
        self.db.commit()
