"""Persistent memory model for GoalOS Memory Manager."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, Float, JSON, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MemoryType(str, Enum):
    """Types of memory GoalOS can store."""

    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    CONVERSATION = "conversation"
    TASK = "task"
    EVENT = "event"
    KNOWLEDGE = "knowledge"
    OUTCOME = "outcome"


class MemoryRecord(Base):
    """A single memory stored by the GoalOS Memory Manager.

    Records are entity-scoped: each memory belongs to a user/entity
    and optionally to a goal/project/conversation context.
    """

    __tablename__ = "memory_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    entity: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    goal: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    project: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    conversation: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[MemoryType] = mapped_column(
        SQLEnum(
            MemoryType,
            values_callable=lambda e: [v.value for v in e],
            name="memory_type",
        ),
        nullable=False,
        index=True,
    )
    importance: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
