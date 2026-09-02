"""Voice call repository for GoalOS.

Provides DB persistence for voice call records and events.
Follows the existing GoalOS repository pattern (per-request SQLAlchemy sessions).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.voice import (
    CallDirection,
    VoiceCallEvent,
    VoiceCallRecord,
    VoiceCallStatus,
)


class VoiceRepository:
    """DB persistence for voice call data."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def create_call(
        self,
        provider: str,
        destination_number: str,
        *,
        caller_number: str | None = None,
        direction: CallDirection = CallDirection.OUTBOUND,
        tts_message: str | None = None,
        language: str | None = None,
        conversation_id: str | None = None,
        campaign_id: str | None = None,
        reference_id: str | None = None,
        external_call_id: str | None = None,
    ) -> VoiceCallRecord:
        """Create a new voice call record."""
        call = VoiceCallRecord(
            provider=provider,
            external_call_id=external_call_id,
            direction=direction,
            destination_number=destination_number,
            caller_number=caller_number,
            status=VoiceCallStatus.QUEUED,
            tts_message=tts_message,
            language=language,
            conversation_id=conversation_id,
            campaign_id=campaign_id,
            reference_id=reference_id,
        )
        self.db.add(call)
        self.db.flush()
        return call

    def get_call(self, call_id: int) -> VoiceCallRecord | None:
        """Get a voice call by ID."""
        return self.db.get(VoiceCallRecord, call_id)

    def get_call_by_external_id(self, external_call_id: str) -> VoiceCallRecord | None:
        """Get a voice call by provider-assigned ID."""
        stmt = select(VoiceCallRecord).where(
            VoiceCallRecord.external_call_id == external_call_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def update_call_status(
        self,
        call_id: int,
        status: VoiceCallStatus,
        *,
        provider_status: str | None = None,
        duration_seconds: int | None = None,
        cost: float | None = None,
        cost_currency: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> VoiceCallRecord | None:
        """Update a voice call's status."""
        call = self.get_call(call_id)
        if call is None:
            return None
        now = datetime.now(timezone.utc)
        call.status = status
        if provider_status:
            call.provider_status = provider_status
        if duration_seconds is not None:
            call.duration_seconds = duration_seconds
        if cost is not None:
            call.cost = cost
        if cost_currency:
            call.cost_currency = cost_currency
        if error_code:
            call.error_code = error_code
        if error_message:
            call.error_message = error_message
        if status == VoiceCallStatus.INITIATED and not call.initiated_at:
            call.initiated_at = now
        elif status == VoiceCallStatus.IN_PROGRESS and not call.answered_at:
            call.answered_at = now
        elif status in (VoiceCallStatus.COMPLETED, VoiceCallStatus.FAILED, VoiceCallStatus.BUSY, VoiceCallStatus.NO_ANSWER):
            call.completed_at = now
        call.updated_at = now
        self.db.flush()
        return call

    def record_event(
        self,
        call_id: int,
        event_type: str,
        provider: str,
        *,
        status: str | None = None,
        duration_seconds: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        raw_payload: str | None = None,
    ) -> VoiceCallEvent:
        """Record a webhook/status event for a call."""
        event = VoiceCallEvent(
            call_id=call_id,
            event_type=event_type,
            provider=provider,
            status=status,
            duration_seconds=duration_seconds,
            error_code=error_code,
            error_message=error_message,
            raw_payload=raw_payload,
        )
        self.db.add(event)
        self.db.flush()
        return event

    def mark_memory_created(self, call_id: int) -> None:
        """Mark that a memory record was created for this call."""
        call = self.get_call(call_id)
        if call:
            call.memory_created = 1
            self.db.flush()

    def list_calls(
        self,
        *,
        limit: int = 50,
        status: VoiceCallStatus | None = None,
        provider: str | None = None,
    ) -> list[VoiceCallRecord]:
        """List voice calls with optional filters."""
        stmt = select(VoiceCallRecord)
        if status:
            stmt = stmt.where(VoiceCallRecord.status == status)
        if provider:
            stmt = stmt.where(VoiceCallRecord.provider == provider)
        stmt = stmt.order_by(VoiceCallRecord.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def get_call_events(self, call_id: int) -> list[VoiceCallEvent]:
        """Get all events for a call."""
        stmt = (
            select(VoiceCallEvent)
            .where(VoiceCallEvent.call_id == call_id)
            .order_by(VoiceCallEvent.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_call_summary(
        self,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Get aggregate call summary."""
        stmt = select(VoiceCallRecord)
        if start_date:
            stmt = stmt.where(VoiceCallRecord.created_at >= start_date)
        if end_date:
            stmt = stmt.where(VoiceCallRecord.created_at <= end_date)
        if provider:
            stmt = stmt.where(VoiceCallRecord.provider == provider)

        records = list(self.db.execute(stmt).scalars().all())
        if not records:
            return {
                "total_calls": 0,
                "completed_calls": 0,
                "failed_calls": 0,
                "avg_duration_seconds": 0,
                "total_cost": 0.0,
                "languages": {},
                "status_breakdown": {},
            }

        total = len(records)
        completed = sum(1 for r in records if r.status == VoiceCallStatus.COMPLETED)
        failed = sum(1 for r in records if r.status == VoiceCallStatus.FAILED)
        durations = [r.duration_seconds for r in records if r.duration_seconds is not None]
        costs = [r.cost for r in records if r.cost is not None]

        languages: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for r in records:
            lang = r.language or "unknown"
            languages[lang] = languages.get(lang, 0) + 1
            st = r.status.value if r.status else "unknown"
            statuses[st] = statuses.get(st, 0) + 1

        return {
            "total_calls": total,
            "completed_calls": completed,
            "failed_calls": failed,
            "completion_rate": round((completed / total) * 100, 1) if total else 0,
            "avg_duration_seconds": int(sum(durations) / len(durations)) if durations else 0,
            "total_duration_seconds": sum(durations),
            "total_cost": round(sum(costs), 4) if costs else 0.0,
            "languages": languages,
            "status_breakdown": statuses,
        }
