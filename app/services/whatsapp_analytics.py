"""WhatsApp Analytics Service for GoalOS.

Provides quality metrics and analytics tracking for WhatsApp conversations.
Integrates with the existing webhook/agent pipeline to record events
without blocking the main flow.

Quality metrics:
- AI resolution rate
- Human handoff rate
- Failed response rate
- Average response time
- Average conversation length
- Language distribution
- Resolution breakdown
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.repositories.whatsapp_analytics_repository import WhatsAppAnalyticsRepository

logger = logging.getLogger(__name__)


def track_inbound_message(
    db: Any,
    conversation_id: int,
    contact_id: int,
    *,
    provider: str = "meta",
    response_latency_ms: int | None = None,
) -> None:
    """Track an inbound message event.

    Called from the webhook/agent pipeline. Non-blocking — errors are logged
    but never raised.
    """
    try:
        repo = WhatsAppAnalyticsRepository(db)
        repo.record_message(
            conversation_id=conversation_id,
            contact_id=contact_id,
            direction="inbound",
            provider=provider,
            response_latency_ms=response_latency_ms,
        )
        db.flush()
    except Exception as exc:
        logger.debug("Analytics track_inbound failed: %s", exc)


def track_outbound_message(
    db: Any,
    conversation_id: int,
    contact_id: int,
    *,
    provider: str = "meta",
    is_ai_response: bool = False,
    is_failed: bool = False,
    response_latency_ms: int | None = None,
) -> None:
    """Track an outbound message event.

    Called from the webhook/agent pipeline. Non-blocking.
    """
    try:
        repo = WhatsAppAnalyticsRepository(db)
        repo.record_message(
            conversation_id=conversation_id,
            contact_id=contact_id,
            direction="outbound",
            provider=provider,
            is_ai_response=is_ai_response,
            is_failed=is_failed,
            response_latency_ms=response_latency_ms,
        )
        db.flush()
    except Exception as exc:
        logger.debug("Analytics track_outbound failed: %s", exc)


def track_handoff(
    db: Any,
    conversation_id: int,
    reason: str,
) -> None:
    """Track a handoff event. Non-blocking."""
    try:
        repo = WhatsAppAnalyticsRepository(db)
        repo.record_handoff(conversation_id=conversation_id, reason=reason)
        db.flush()
    except Exception as exc:
        logger.debug("Analytics track_handoff failed: %s", exc)


def set_resolution(
    db: Any,
    conversation_id: int,
    status: str,
) -> None:
    """Set conversation resolution status. Non-blocking."""
    try:
        repo = WhatsAppAnalyticsRepository(db)
        repo.set_resolution(conversation_id=conversation_id, status=status)
        db.flush()
    except Exception as exc:
        logger.debug("Analytics set_resolution failed: %s", exc)


def set_language(
    db: Any,
    conversation_id: int,
    language: str,
) -> None:
    """Set detected language. Non-blocking."""
    try:
        repo = WhatsAppAnalyticsRepository(db)
        repo.set_language(conversation_id=conversation_id, language=language)
        db.flush()
    except Exception as exc:
        logger.debug("Analytics set_language failed: %s", exc)


def get_analytics_summary(
    db: Any,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    contact_id: int | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Get aggregate analytics summary with date-range filtering.

    Returns a complete summary dict with all quality metrics.
    """
    try:
        repo = WhatsAppAnalyticsRepository(db)
        return repo.get_summary(
            start_date=start_date,
            end_date=end_date,
            contact_id=contact_id,
            provider=provider,
        )
    except Exception as exc:
        logger.warning("Analytics summary failed: %s", exc)
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
            "error": str(exc),
        }


def get_conversation_analytics(
    db: Any,
    conversation_id: int,
) -> dict[str, Any] | None:
    """Get analytics for a specific conversation."""
    try:
        repo = WhatsAppAnalyticsRepository(db)
        analytics = repo.get(conversation_id)
        if analytics is None:
            return None
        return {
            "conversation_id": analytics.conversation_id,
            "total_messages": analytics.total_messages,
            "inbound_count": analytics.inbound_count,
            "outbound_count": analytics.outbound_count,
            "ai_response_count": analytics.ai_response_count,
            "failed_response_count": analytics.failed_response_count,
            "avg_response_latency_ms": analytics.avg_response_latency_ms,
            "handoff_count": analytics.handoff_count,
            "last_handoff_reason": analytics.last_handoff_reason,
            "ai_resolution_rate": analytics.ai_resolution_rate,
            "conversation_duration_seconds": analytics.conversation_duration_seconds,
            "resolution_status": analytics.resolution_status,
            "detected_language": analytics.detected_language,
            "first_message_at": analytics.first_message_at.isoformat() if analytics.first_message_at else None,
            "last_message_at": analytics.last_message_at.isoformat() if analytics.last_message_at else None,
        }
    except Exception as exc:
        logger.warning("Conversation analytics failed: %s", exc)
        return None


def list_conversation_analytics(
    db: Any,
    *,
    limit: int = 50,
    contact_id: int | None = None,
) -> list[dict[str, Any]]:
    """List per-conversation analytics."""
    try:
        repo = WhatsAppAnalyticsRepository(db)
        records = repo.list_conversation_analytics(limit=limit, contact_id=contact_id)
        return [
            {
                "conversation_id": r.conversation_id,
                "total_messages": r.total_messages,
                "ai_resolution_rate": r.ai_resolution_rate,
                "handoff_count": r.handoff_count,
                "resolution_status": r.resolution_status,
                "detected_language": r.detected_language,
                "last_message_at": r.last_message_at.isoformat() if r.last_message_at else None,
            }
            for r in records
        ]
    except Exception as exc:
        logger.warning("List analytics failed: %s", exc)
        return []
