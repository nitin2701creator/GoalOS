"""WhatsApp Analytics repository for GoalOS.

Provides DB persistence for conversation analytics.
Follows the existing GoalOS repository pattern (per-request SQLAlchemy sessions).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.whatsapp import (
    WhatsAppAnalytics,
    WhatsAppConversation,
)


class WhatsAppAnalyticsRepository:
    """DB persistence for WhatsApp analytics data."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_or_create(self, conversation_id: int, contact_id: int, provider: str = "meta") -> WhatsAppAnalytics:
        """Get existing analytics or create a new one for a conversation."""
        stmt = select(WhatsAppAnalytics).where(
            WhatsAppAnalytics.conversation_id == conversation_id
        )
        analytics = self.db.execute(stmt).scalar_one_or_none()
        if analytics is None:
            analytics = WhatsAppAnalytics(
                conversation_id=conversation_id,
                contact_id=contact_id,
                provider=provider,
                first_message_at=datetime.now(timezone.utc),
            )
            self.db.add(analytics)
            self.db.flush()
        return analytics

    def get(self, conversation_id: int) -> WhatsAppAnalytics | None:
        """Get analytics for a conversation."""
        stmt = select(WhatsAppAnalytics).where(
            WhatsAppAnalytics.conversation_id == conversation_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def record_message(
        self,
        conversation_id: int,
        contact_id: int,
        direction: str,
        *,
        provider: str = "meta",
        response_latency_ms: int | None = None,
        is_ai_response: bool = False,
        is_failed: bool = False,
    ) -> WhatsAppAnalytics:
        """Record a message event in analytics."""
        analytics = self.get_or_create(conversation_id, contact_id, provider)
        now = datetime.now(timezone.utc)

        analytics.total_messages = (analytics.total_messages or 0) + 1
        analytics.last_message_at = now

        if direction == "inbound":
            analytics.inbound_count = (analytics.inbound_count or 0) + 1
        else:
            analytics.outbound_count = (analytics.outbound_count or 0) + 1

        if is_ai_response:
            analytics.ai_response_count = (analytics.ai_response_count or 0) + 1
        if is_failed:
            analytics.failed_response_count = (analytics.failed_response_count or 0) + 1

        # Response latency tracking
        if response_latency_ms is not None and response_latency_ms > 0:
            analytics.total_response_latency_ms = (
                (analytics.total_response_latency_ms or 0) + response_latency_ms
            )
            analytics.response_latency_samples = (
                (analytics.response_latency_samples or 0) + 1
            )
            analytics.avg_response_latency_ms = int(
                analytics.total_response_latency_ms / analytics.response_latency_samples
            )

        # Calculate AI resolution rate
        total_responses = (analytics.ai_response_count or 0) + (analytics.failed_response_count or 0)
        if total_responses > 0:
            analytics.ai_resolution_rate = int(
                ((analytics.ai_response_count or 0) / total_responses) * 100
            )

        # Conversation duration
        if analytics.first_message_at:
            first = analytics.first_message_at
            if first.tzinfo is None:
                first = first.replace(tzinfo=timezone.utc)
            delta = now - first
            analytics.conversation_duration_seconds = int(delta.total_seconds())

        self.db.flush()
        return analytics

    def record_handoff(
        self,
        conversation_id: int,
        reason: str,
        *,
        contact_id: int | None = None,
    ) -> WhatsAppAnalytics | None:
        """Record a handoff event in analytics."""
        analytics = self.get(conversation_id)
        if analytics is None:
            # Create analytics on demand if it doesn't exist yet
            if contact_id is None:
                # Look up contact_id from conversation
                conv = self.db.get(WhatsAppConversation, conversation_id)
                if conv is None:
                    return None
                contact_id = conv.contact_id
            analytics = self.get_or_create(conversation_id, contact_id)

        analytics.handoff_count = (analytics.handoff_count or 0) + 1
        analytics.last_handoff_reason = reason

        # Append reason to JSON list
        try:
            reasons = json.loads(analytics.handoff_reasons or "[]")
        except (json.JSONDecodeError, TypeError):
            reasons = []
        reasons.append({"reason": reason, "at": datetime.now(timezone.utc).isoformat()})
        analytics.handoff_reasons = json.dumps(reasons[-20:])  # Keep last 20

        self.db.flush()
        return analytics

    def set_resolution(
        self,
        conversation_id: int,
        status: str,
        contact_id: int | None = None,
    ) -> WhatsAppAnalytics | None:
        """Set conversation resolution status."""
        analytics = self.get(conversation_id)
        if analytics is None:
            if contact_id is None:
                conv = self.db.get(WhatsAppConversation, conversation_id)
                if conv is None:
                    return None
                contact_id = conv.contact_id
            analytics = self.get_or_create(conversation_id, contact_id)
        analytics.resolution_status = status
        self.db.flush()
        return analytics

    def set_language(self, conversation_id: int, language: str, contact_id: int | None = None) -> WhatsAppAnalytics | None:
        """Set detected language for a conversation."""
        analytics = self.get(conversation_id)
        if analytics is None:
            if contact_id is None:
                conv = self.db.get(WhatsAppConversation, conversation_id)
                if conv is None:
                    return None
                contact_id = conv.contact_id
            analytics = self.get_or_create(conversation_id, contact_id)
        analytics.detected_language = language
        self.db.flush()
        return analytics

    def get_summary(
        self,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        contact_id: int | None = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Get aggregate analytics summary with optional date-range filtering."""
        stmt = select(WhatsAppAnalytics)

        if start_date:
            stmt = stmt.where(WhatsAppAnalytics.created_at >= start_date)
        if end_date:
            stmt = stmt.where(WhatsAppAnalytics.created_at <= end_date)
        if contact_id:
            stmt = stmt.where(WhatsAppAnalytics.contact_id == contact_id)
        if provider:
            stmt = stmt.where(WhatsAppAnalytics.provider == provider)

        records = list(self.db.execute(stmt).scalars().all())

        if not records:
            return {
                "total_conversations": 0,
                "total_messages": 0,
                "avg_messages_per_conversation": 0,
                "ai_resolution_rate": 0,
                "handoff_rate": 0,
                "failed_response_rate": 0,
                "avg_response_latency_ms": 0,
                "avg_conversation_duration_seconds": 0,
                "languages": {},
                "resolution_breakdown": {},
            }

        total_conversations = len(records)
        total_messages = sum(r.total_messages or 0 for r in records)
        total_ai = sum(r.ai_response_count or 0 for r in records)
        total_failed = sum(r.failed_response_count or 0 for r in records)
        total_handoffs = sum(r.handoff_count or 0 for r in records)
        total_latency = sum(r.total_response_latency_ms or 0 for r in records)
        latency_samples = sum(r.response_latency_samples or 0 for r in records)
        total_duration = sum(r.conversation_duration_seconds or 0 for r in records)

        # Language distribution
        languages: dict[str, int] = {}
        for r in records:
            lang = r.detected_language or "unknown"
            languages[lang] = languages.get(lang, 0) + 1

        # Resolution breakdown
        resolutions: dict[str, int] = {}
        for r in records:
            res = r.resolution_status or "pending"
            resolutions[res] = resolutions.get(res, 0) + 1

        total_responses = total_ai + total_failed
        return {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "avg_messages_per_conversation": round(total_messages / total_conversations, 1) if total_conversations else 0,
            "ai_resolution_rate": round((total_ai / total_responses * 100), 1) if total_responses else 0,
            "handoff_rate": round((total_handoffs / total_conversations * 100), 1) if total_conversations else 0,
            "failed_response_rate": round((total_failed / total_responses * 100), 1) if total_responses else 0,
            "avg_response_latency_ms": int(total_latency / latency_samples) if latency_samples else 0,
            "avg_conversation_duration_seconds": int(total_duration / total_conversations) if total_conversations else 0,
            "languages": languages,
            "resolution_breakdown": resolutions,
        }

    def list_conversation_analytics(
        self,
        *,
        limit: int = 50,
        contact_id: int | None = None,
    ) -> list[WhatsAppAnalytics]:
        """List per-conversation analytics."""
        stmt = select(WhatsAppAnalytics)
        if contact_id:
            stmt = stmt.where(WhatsAppAnalytics.contact_id == contact_id)
        stmt = stmt.order_by(WhatsAppAnalytics.last_message_at.desc().nullslast()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())
