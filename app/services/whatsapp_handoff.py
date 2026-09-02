"""WhatsApp Human Handoff Service for GoalOS.

Detects when a conversation should be escalated to a human operator,
manages handoff state transitions, and provides conversation context
for human operators.

Escalation triggers:
- Explicit user request (e.g. "human", "agent", "call me", "speak to someone")
- Repeated low-confidence AI responses
- Unsupported requests
- Configurable confidence threshold
- Configurable escalation keywords
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.db.models.whatsapp import HandoffState, WhatsAppHandoff
from app.repositories.whatsapp_repository import WhatsAppRepository

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default escalation keywords — messages containing these trigger handoff
_DEFAULT_ESCALATION_KEYWORDS = [
    "human",
    "agent",
    "person",
    "someone",
    "speak to someone",
    "talk to someone",
    "call me",
    "real person",
    "operator",
    "manager",
    "supervisor",
    "escalate",
    "help from a person",
    "not a bot",
    "not a robot",
    "真人",
    "人工客服",
    "转人工",
]


def _get_escalation_keywords() -> list[str]:
    """Return configured escalation keywords."""
    custom = os.getenv("WHATSAPP_HANDOFF_KEYWORDS", "")
    if custom.strip():
        return [k.strip().lower() for k in custom.split(",") if k.strip()]
    return [k.lower() for k in _DEFAULT_ESCALATION_KEYWORDS]


def _get_confidence_threshold() -> float:
    """Return the confidence threshold below which AI triggers escalation."""
    try:
        return float(os.getenv("WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD", "0.3"))
    except (ValueError, TypeError):
        return 0.3


def _get_max_consecutive_failures() -> int:
    """Return the max consecutive low-confidence responses before escalation."""
    try:
        return int(os.getenv("WHATSAPP_HANDOFF_MAX_FAILURES", "3"))
    except (ValueError, TypeError):
        return 3


# ---------------------------------------------------------------------------
# Escalation detection
# ---------------------------------------------------------------------------

# Track consecutive low-confidence responses per conversation
_conversation_failures: dict[int, int] = {}


def detect_escalation_trigger(
    content: str,
    conversation_id: int,
    ai_confidence: float | None = None,
) -> dict[str, Any]:
    """Analyze an inbound message to determine if human handoff is needed.

    Returns:
        {
            "should_escalate": bool,
            "reason": str | None,
            "detail": str | None,
        }
    """
    if not content:
        return {"should_escalate": False, "reason": None, "detail": None}

    content_lower = content.strip().lower()

    # 1. Check explicit escalation keywords
    keywords = _get_escalation_keywords()
    for keyword in keywords:
        if keyword in content_lower:
            return {
                "should_escalate": True,
                "reason": "explicit_user_request",
                "detail": f"User message contains escalation keyword: '{keyword}'",
            }

    # 2. Check confidence threshold
    if ai_confidence is not None and ai_confidence < _get_confidence_threshold():
        _conversation_failures[conversation_id] = (
            _conversation_failures.get(conversation_id, 0) + 1
        )
        max_failures = _get_max_consecutive_failures()
        if _conversation_failures[conversation_id] >= max_failures:
            return {
                "should_escalate": True,
                "reason": "low_confidence",
                "detail": (
                    f"AI confidence {ai_confidence:.2f} is below threshold "
                    f"{_get_confidence_threshold():.2f} for "
                    f"{_conversation_failures[conversation_id]} consecutive messages"
                ),
            }
    else:
        # Reset failure count on good response
        _conversation_failures.pop(conversation_id, None)

    return {"should_escalate": False, "reason": None, "detail": None}


# ---------------------------------------------------------------------------
# Handoff state management
# ---------------------------------------------------------------------------


def should_block_ai_reply(db: Any, conversation_id: int) -> bool:
    """Check if AI auto-reply should be blocked for this conversation.

    AI replies are blocked when:
    - Handoff state is HUMAN_REQUESTED or HUMAN_ACTIVE
    """
    repo = WhatsAppRepository(db)
    handoff = repo.get_handoff(conversation_id)
    if handoff is None:
        return False
    return handoff.state in (HandoffState.HUMAN_REQUESTED, HandoffState.HUMAN_ACTIVE)


def request_handoff(
    db: Any,
    conversation_id: int,
    reason: str = "explicit_user_request",
    detail: str | None = None,
) -> dict[str, Any]:
    """Request human handoff for a conversation.

    Transitions the conversation from AI_ACTIVE to HUMAN_REQUESTED.
    If already in HUMAN_REQUESTED or HUMAN_ACTIVE, returns current state.
    """
    repo = WhatsAppRepository(db)
    handoff = repo.get_handoff(conversation_id)

    if handoff and handoff.state in (
        HandoffState.HUMAN_REQUESTED,
        HandoffState.HUMAN_ACTIVE,
    ):
        return {
            "status": "already_in_handoff",
            "state": handoff.state.value,
            "requested_at": handoff.requested_at.isoformat() if handoff.requested_at else None,
        }

    # Create or reset handoff to HUMAN_REQUESTED
    handoff = repo.create_handoff(
        conversation_id=conversation_id,
        state=HandoffState.HUMAN_REQUESTED,
        escalation_reason=reason,
        escalation_detail=detail,
    )
    db.commit()

    logger.info(
        "Handoff requested for conversation %d: reason=%s",
        conversation_id,
        reason,
    )
    return {
        "status": "handoff_requested",
        "state": handoff.state.value,
        "handoff_id": handoff.id,
        "requested_at": handoff.requested_at.isoformat() if handoff.requested_at else None,
        "reason": reason,
    }


def activate_human_handling(
    db: Any,
    conversation_id: int,
    assigned_to: str | None = None,
) -> dict[str, Any]:
    """A human operator takes over the conversation.

    Transitions from HUMAN_REQUESTED to HUMAN_ACTIVE.
    """
    repo = WhatsAppRepository(db)
    handoff = repo.transition_handoff(
        conversation_id=conversation_id,
        new_state=HandoffState.HUMAN_ACTIVE,
        assigned_to=assigned_to,
    )
    if handoff is None:
        # No handoff record — create one directly in HUMAN_ACTIVE
        handoff = repo.create_handoff(
            conversation_id=conversation_id,
            state=HandoffState.HUMAN_ACTIVE,
        )
    db.commit()

    logger.info("Human handling activated for conversation %d", conversation_id)
    return {
        "status": "human_active",
        "state": handoff.state.value,
        "assigned_to": handoff.assigned_to,
        "activated_at": handoff.activated_at.isoformat() if handoff.activated_at else None,
    }


def resolve_handoff(
    db: Any,
    conversation_id: int,
    resolution_notes: str | None = None,
) -> dict[str, Any]:
    """Resolve a handoff and return conversation to AI control.

    Transitions from HUMAN_ACTIVE or HUMAN_REQUESTED to RESOLVED.
    """
    repo = WhatsAppRepository(db)
    handoff = repo.transition_handoff(
        conversation_id=conversation_id,
        new_state=HandoffState.RESOLVED,
        resolution_notes=resolution_notes,
    )
    if handoff is None:
        return {"status": "no_handoff_found"}

    db.commit()
    logger.info("Handoff resolved for conversation %d", conversation_id)
    return {
        "status": "resolved",
        "state": handoff.state.value,
        "resolved_at": handoff.resolved_at.isoformat() if handoff.resolved_at else None,
        "resolution_notes": handoff.resolution_notes,
    }


def return_to_ai(db: Any, conversation_id: int) -> dict[str, Any]:
    """Return a resolved conversation back to AI-active state.

    Clears the handoff record so the AI can resume responding.
    """
    repo = WhatsAppRepository(db)
    handoff = repo.transition_handoff(
        conversation_id=conversation_id,
        new_state=HandoffState.AI_ACTIVE,
    )
    if handoff is None:
        return {"status": "no_handoff_found"}

    # Reset failure counter for this conversation
    _conversation_failures.pop(conversation_id, None)

    db.commit()
    return {
        "status": "ai_active",
        "state": handoff.state.value,
    }


# ---------------------------------------------------------------------------
# Conversation context for human operators
# ---------------------------------------------------------------------------


def get_handoff_context(db: Any, conversation_id: int) -> dict[str, Any]:
    """Return conversation context for a human operator taking over.

    Includes the handoff record, recent messages, and contact info.
    Does NOT expose WhatsApp tokens or credentials.
    """
    repo = WhatsAppRepository(db)
    handoff = repo.get_handoff(conversation_id)
    conv = repo.get_conversation(conversation_id)

    if conv is None:
        return {"error": "Conversation not found"}

    contact = None
    from app.db.models.whatsapp import WhatsAppContact

    contact = db.get(WhatsAppContact, conv.contact_id) if conv.contact_id else None

    messages = repo.list_messages(conversation_id=conversation_id, limit=50)

    return {
        "conversation_id": conversation_id,
        "handoff": {
            "state": handoff.state.value if handoff else "no_handoff",
            "reason": handoff.escalation_reason if handoff else None,
            "detail": handoff.escalation_detail if handoff else None,
            "assigned_to": handoff.assigned_to if handoff else None,
            "requested_at": handoff.requested_at.isoformat() if handoff and handoff.requested_at else None,
            "activated_at": handoff.activated_at.isoformat() if handoff and handoff.activated_at else None,
            "resolution_notes": handoff.resolution_notes if handoff else None,
        },
        "contact": {
            "name": contact.name if contact else None,
            "phone_number": contact.phone_number if contact else None,
            "provider": contact.provider if contact else None,
        },
        "messages": [
            {
                "direction": m.direction.value,
                "content": m.content,
                "media_type": m.media_type.value,
                "status": m.status.value,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "message_count": len(messages),
    }


def get_pending_handoffs(db: Any) -> list[dict[str, Any]]:
    """List all conversations waiting for human attention."""
    repo = WhatsAppRepository(db)
    handoffs = repo.list_handoffs(state=HandoffState.HUMAN_REQUESTED, limit=100)
    return [
        {
            "handoff_id": h.id,
            "conversation_id": h.conversation_id,
            "state": h.state.value,
            "reason": h.escalation_reason,
            "detail": h.escalation_detail,
            "requested_at": h.requested_at.isoformat() if h.requested_at else None,
        }
        for h in handoffs
    ]
