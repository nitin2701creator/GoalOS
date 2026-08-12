"""Persistence repository for ingested webhook events."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.event import EventRecord


class EventRepository:
    """Database access for persisted webhook event records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, values: dict[str, Any]) -> EventRecord:
        event = EventRecord(**values)
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get(self, event_id: uuid.UUID) -> EventRecord | None:
        statement = select(EventRecord).where(EventRecord.id == event_id)
        return self.db.scalars(statement).one_or_none()

    def get_by_event_id(self, event_id: str, source: str) -> EventRecord | None:
        """Return a previously ingested event with the same source event id."""
        statement = select(EventRecord).where(
            EventRecord.event_id == event_id,
            EventRecord.source == source,
        )
        return self.db.scalars(statement).one_or_none()

    def list(self, limit: int = 100) -> Sequence[EventRecord]:
        statement = select(EventRecord).order_by(EventRecord.received_at.desc()).limit(limit)
        return self.db.scalars(statement).all()

    def update(self, event: EventRecord, updates: dict[str, Any]) -> EventRecord:
        for field, value in updates.items():
            setattr(event, field, value)
        self.db.commit()
        self.db.refresh(event)
        return event

    def count(self) -> int:
        from sqlalchemy import func

        return int(self.db.scalar(select(func.count()).select_from(EventRecord)) or 0)
