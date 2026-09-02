"""API schemas for the GoalOS Memory Manager."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MemoryRememberRequest(BaseModel):
    """Request to store a new memory."""

    entity: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    memory_type: str = Field(default="knowledge", description="fact|preference|decision|conversation|task|event|knowledge|outcome")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    goal: str | None = None
    project: str | None = None
    conversation: str | None = None
    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryResponse(BaseModel):
    """API representation of a memory."""

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
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    accessed_at: datetime | None = None

    model_config = {"from_attributes": True}


class MemorySearchRequest(BaseModel):
    """Request to search/recall memories."""

    entity: str = Field(min_length=1)
    query: str = ""
    goal: str | None = None
    project: str | None = None
    conversation: str | None = None
    memory_type: str | None = None
    min_importance: float = Field(default=0.0, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ContextResponse(BaseModel):
    """Aggregated context for an entity."""

    entity: str
    recent_memories: list[MemoryResponse]
    key_facts: list[MemoryResponse]
    active_goals: list[str]
    total_count: int


class MemoryForgetRequest(BaseModel):
    """Request to soft-delete a memory."""

    memory_id: UUID
