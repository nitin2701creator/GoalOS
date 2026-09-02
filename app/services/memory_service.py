"""GoalOS Memory Manager — the main memory service.

Provides remember(), recall(), search(), forget(), and get_context()
using the SQLAlchemy database directly. The provider interface allows
swapping in TencentDB Agent Memory, Mem0, or pgvector-backed providers
later without changing callers.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.db.models.memory import MemoryType
from app.memory import (
    BaseMemoryProvider,
    ContextResult,
    MemoryQuery,
    MemoryResult,
)
from app.repositories.memory_repository import MemoryRepository


def _to_result(record) -> MemoryResult:
    """Convert a DB record to a MemoryResult."""
    return MemoryResult(
        id=record.id,
        entity=record.entity,
        content=record.content,
        memory_type=record.memory_type.value if hasattr(record.memory_type, "value") else str(record.memory_type),
        importance=record.importance,
        confidence=record.confidence,
        source=record.source,
        goal=record.goal,
        project=record.project,
        conversation=record.conversation,
        metadata_json=record.metadata_json or {},
        created_at=record.created_at,
        accessed_at=record.accessed_at,
    )


class MemoryProvider(BaseMemoryProvider):
    """SQLAlchemy-based memory provider (default backend).

    Stores memories in the existing GoalOS database. Can be swapped for
    a pgvector, TencentDB, or Mem0 provider by changing the constructor
    in the service layer.
    """

    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def remember(
        self,
        entity: str,
        content: str,
        memory_type: str = "knowledge",
        *,
        importance: float = 0.5,
        confidence: float = 1.0,
        goal: str | None = None,
        project: str | None = None,
        conversation: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryResult:
        try:
            mem_type = MemoryType(memory_type)
        except ValueError:
            mem_type = MemoryType.KNOWLEDGE
        record = self.repository.create(
            {
                "entity": entity,
                "content": content,
                "memory_type": mem_type,
                "importance": importance,
                "confidence": confidence,
                "goal": goal,
                "project": project,
                "conversation": conversation,
                "source": source,
                "metadata_json": metadata or {},
            }
        )
        return _to_result(record)

    def recall(self, memory_id: UUID) -> MemoryResult | None:
        record = self.repository.get(memory_id)
        if record is None:
            return None
        return _to_result(record)

    def search(self, query: MemoryQuery) -> list[MemoryResult]:
        records = self.repository.search(
            query.entity,
            query=query.query,
            goal=query.goal,
            project=query.project,
            conversation=query.conversation,
            memory_type=query.memory_type,
            min_importance=query.min_importance,
            min_confidence=query.min_confidence,
            limit=query.limit,
            offset=query.offset,
        )
        return [_to_result(r) for r in records]

    def forget(self, memory_id: UUID) -> bool:
        return self.repository.forget(memory_id)

    def get_context(self, entity: str, limit: int = 20) -> ContextResult:
        recent = self.repository.search(entity, limit=limit)
        key_facts = self.repository.search(
            entity, memory_type="fact", min_importance=0.5, limit=10
        )
        active_goals = self.repository.active_goals_for_entity(entity)
        total = self.repository.count_for_entity(entity)
        return ContextResult(
            entity=entity,
            recent_memories=[_to_result(r) for r in recent],
            key_facts=[_to_result(r) for r in key_facts],
            active_goals=active_goals,
            total_count=total,
        )
