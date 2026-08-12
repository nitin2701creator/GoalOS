"""API schemas for persisted webhook events."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.db.models.event import EventStatus


class EventRecordResponse(BaseModel):
    """API representation of one persisted webhook event."""

    id: UUID
    source: str
    event_type: str
    event_id: str | None = None
    object_type: str | None = None
    object_id: str | None = None
    payload: dict[str, Any] = {}
    signature_valid: bool
    status: EventStatus
    error: str | None = None
    received_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookIngestResponse(BaseModel):
    """Structured result of ingesting one webhook request.

    ``accepted`` is True only for a valid, non-duplicate, persisted event.
    Duplicate replays return ``accepted=False`` with ``reason`` describing
    the outcome — never a fake success.
    """

    accepted: bool
    status: str
    event_id: str | None = None
    event_type: str | None = None
    reason: str | None = None
