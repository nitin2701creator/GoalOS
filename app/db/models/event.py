"""Webhook/event persistence model.

Structured records of every webhook event GoalOS ingests (currently Twenty
CRM record-created/updated/deleted events). Persisted events are the
foundation for routing events into the existing workflow/scheduler/execution
architecture later — nothing is ever acknowledged without a durable record.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventStatus(str, Enum):
    """Lifecycle states of a persisted event."""

    RECEIVED = "received"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    PROCESSED = "processed"
    FAILED = "failed"


class EventRecord(Base):
    """One persisted webhook event with its validation outcome."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    object_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        SQLEnum(
            EventStatus,
            values_callable=lambda enum_class: [item.value for item in enum_class],
            name="event_status",
        ),
        nullable=False,
        default=EventStatus.RECEIVED,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
