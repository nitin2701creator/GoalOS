"""Memory provider abstraction for GoalOS Memory Manager.

Implement this interface to add a new memory backend (PostgreSQL+pgvector,
TencentDB Agent Memory, Mem0, etc.). The default MemoryProvider uses the
existing SQLAlchemy database directly.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class MemoryQuery:
    """Parameters for recalling/searching memories."""

    entity: str
    query: str = ""
    goal: str | None = None
    project: str | None = None
    conversation: str | None = None
    memory_type: str | None = None
    min_importance: float = 0.0
    min_confidence: float = 0.0
    limit: int = 20
    offset: int = 0


@dataclass(frozen=True, slots=True)
class MemoryResult:
    """One memory recalled from storage."""

    id: UUID
    entity: str
    content: str
    memory_type: str
    importance: float
    confidence: float
    source: str | None = None
    goal: str | None = None
    project: str | None = None
    conversation: str | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None
    accessed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ContextResult:
    """Aggregated context for an entity, for agent consumption."""

    entity: str
    recent_memories: list[MemoryResult]
    key_facts: list[MemoryResult]
    active_goals: list[str]
    total_count: int


class BaseMemoryProvider(abc.ABC):
    """Abstract memory provider interface.

    Any backend (PostgreSQL+pgvector, TencentDB, Mem0, etc.) can be
    plugged in by subclassing this and implementing the methods.
    """

    @abc.abstractmethod
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
        """Store a new memory."""

    @abc.abstractmethod
    def recall(self, memory_id: UUID) -> MemoryResult | None:
        """Retrieve a single memory by ID."""

    @abc.abstractmethod
    def search(self, query: MemoryQuery) -> list[MemoryResult]:
        """Search/recall memories matching the query."""

    @abc.abstractmethod
    def forget(self, memory_id: UUID) -> bool:
        """Soft-delete a memory. Returns True if found and deleted."""

    @abc.abstractmethod
    def get_context(self, entity: str, limit: int = 20) -> ContextResult:
        """Get aggregated context for an entity."""
