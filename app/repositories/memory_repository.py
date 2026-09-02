"""Memory persistence repository for GoalOS Memory Manager."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from app.db.models.memory import MemoryRecord, MemoryType


class MemoryRepository:
    """Database access for memory records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict) -> MemoryRecord:
        record = MemoryRecord(**values)
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get(self, memory_id: uuid.UUID) -> MemoryRecord | None:
        stmt = select(MemoryRecord).where(
            MemoryRecord.id == memory_id,
            MemoryRecord.is_deleted == False,  # noqa: E712
        )
        return self.db.scalars(stmt).one_or_none()

    def search(
        self,
        entity: str,
        *,
        query: str = "",
        goal: str | None = None,
        project: str | None = None,
        conversation: str | None = None,
        memory_type: str | None = None,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[MemoryRecord]:
        stmt = (
            select(MemoryRecord)
            .where(
                MemoryRecord.entity == entity,
                MemoryRecord.is_deleted == False,  # noqa: E712
            )
            .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
        )
        if query:
            stmt = stmt.where(MemoryRecord.content.contains(query))
        if goal:
            stmt = stmt.where(MemoryRecord.goal == goal)
        if project:
            stmt = stmt.where(MemoryRecord.project == project)
        if conversation:
            stmt = stmt.where(MemoryRecord.conversation == conversation)
        if memory_type:
            stmt = stmt.where(MemoryRecord.memory_type == memory_type)
        if min_importance > 0:
            stmt = stmt.where(MemoryRecord.importance >= min_importance)
        if min_confidence > 0:
            stmt = stmt.where(MemoryRecord.confidence >= min_confidence)
        stmt = stmt.offset(offset).limit(limit)
        return self.db.scalars(stmt).all()

    def count_for_entity(self, entity: str) -> int:
        stmt = select(func.count()).select_from(MemoryRecord).where(
            MemoryRecord.entity == entity,
            MemoryRecord.is_deleted == False,  # noqa: E712
        )
        return self.db.scalar(stmt) or 0

    def forget(self, memory_id: uuid.UUID) -> bool:
        stmt = (
            update(MemoryRecord)
            .where(MemoryRecord.id == memory_id, MemoryRecord.is_deleted == False)
            .values(is_deleted=True)
        )
        result = self.db.execute(stmt)
        self.db.commit()
        return result.rowcount > 0

    def active_goals_for_entity(self, entity: str) -> list[str]:
        """Return distinct non-null goals for an entity."""
        stmt = (
            select(MemoryRecord.goal)
            .where(
                MemoryRecord.entity == entity,
                MemoryRecord.is_deleted == False,
                MemoryRecord.goal.isnot(None),
            )
            .distinct()
            .limit(50)
        )
        return [row[0] for row in self.db.execute(stmt).all() if row[0]]
