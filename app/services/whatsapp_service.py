"""GoalOS WhatsApp Service — provider-neutral orchestration layer.

Provides send_message() and process_inbound() that dispatch to the active
WhatsApp provider via the factory. Manages DB persistence and feeds
conversation events into the GoalOS memory system.

WhatsApp message → GoalOS conversation/event → Memory service → long-term memory
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.db.models.memory import MemoryType
from app.db.models.whatsapp import (
    MessageDirection,
    MessageStatus,
    MediaType,
)
from app.integrations.whatsapp.base import BaseWhatsAppAdapter
from app.integrations.whatsapp.factory import get_active_provider
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.services.action_policy import (
    ActionPolicyEngine,
    PolicyDecision,
    SPRINT1_ACTIONS,
)

logger = logging.getLogger(__name__)

#: Module-level policy engine.
_policy = ActionPolicyEngine()
_policy.register_many(SPRINT1_ACTIONS)

# Mapping from provider-neutral media types to DB enums
_MEDIA_MAP = {
    WhatsAppMediaType.TEXT: MediaType.TEXT,
    WhatsAppMediaType.IMAGE: MediaType.IMAGE,
    WhatsAppMediaType.VIDEO: MediaType.VIDEO,
    WhatsAppMediaType.AUDIO: MediaType.AUDIO,
    WhatsAppMediaType.DOCUMENT: MediaType.DOCUMENT,
    WhatsAppMediaType.LOCATION: MediaType.LOCATION,
    WhatsAppMediaType.CONTACT: MediaType.CONTACT,
    WhatsAppMediaType.STICKER: MediaType.STICKER,
}


def _get_provider() -> BaseWhatsAppAdapter | None:
    """Resolve the active WhatsApp provider."""
    return get_active_provider()


def send_message(
    destination_number: str,
    message: str = "",
    *,
    media_url: str | None = None,
    media_type: WhatsAppMediaType = WhatsAppMediaType.TEXT,
    caption: str | None = None,
    has_approved_context: bool = False,
    db: Any = None,
) -> dict[str, Any]:
    """Send an outbound WhatsApp message through the active provider.

    Returns a structured result dict suitable for capability execution.
    Never raises — errors are returned in the result.
    """
    # Policy check first
    policy = _policy.evaluate("send_whatsapp", has_approved_context=has_approved_context)
    if policy.decision == PolicyDecision.DENIED:
        return {"status": "DENIED", "error": policy.reason, "policy": policy.reason}
    if policy.decision == PolicyDecision.APPROVAL_REQUIRED:
        return {"status": "APPROVAL_REQUIRED", "error": policy.reason, "policy": policy.reason}

    provider = _get_provider()
    if provider is None:
        return {
            "status": "INTEGRATION_NOT_CONFIGURED",
            "error": (
                "INTEGRATION_NOT_CONFIGURED: no WHATSAPP_PROVIDER configured. "
                "Set WHATSAPP_PROVIDER to 'openwa' and configure OPENWA_API_URL."
            ),
        }
    if not provider.is_configured:
        return {
            "status": "INTEGRATION_NOT_CONFIGURED",
            "error": (
                f"INTEGRATION_NOT_CONFIGURED: {provider.name} "
                "credentials are missing. Set OPENWA_API_URL."
            ),
        }

    request = SendMessageRequest(
        destination_number=destination_number,
        message=message,
        media_url=media_url,
        media_type=media_type,
        caption=caption,
    )

    result: SendMessageResponse = provider.send_message(request)

    # Persist to DB if session provided
    if db is not None and result.status in (WhatsAppStatus.QUEUED, WhatsAppStatus.SENT):
        try:
            repo = WhatsAppRepository(db)
            contact = repo.get_or_create_contact(
                provider=provider.name,
                external_id=destination_number,
                phone_number=destination_number,
            )
            conv = repo.get_or_create_conversation(
                provider=provider.name,
                contact_id=contact.id,
                direction=MessageDirection.OUTBOUND,
            )
            msg = repo.create_message(
                conversation_id=conv.id,
                provider=provider.name,
                direction=MessageDirection.OUTBOUND,
                content=message or caption,
                media_type=_MEDIA_MAP.get(media_type, MediaType.TEXT),
                media_url=media_url,
                caption=caption,
                external_message_id=result.external_message_id,
                status=MessageStatus.SENT,
            )
            db.commit()

            # Feed into GoalOS memory system
            _feed_memory(
                db=db,
                contact_name=str(contact.name or destination_number),
                direction="outbound",
                content=message or f"[{media_type.value}]",
                provider=provider.name,
            )
        except Exception as exc:
            logger.warning("Failed to persist WhatsApp message: %s", exc)

    return {
        "provider": result.provider,
        "external_message_id": result.external_message_id,
        "status": result.status.value,
        "error": result.error,
        "provider_metadata": result.provider_metadata,
    }


def process_inbound(
    webhook_event: WhatsAppWebhookEvent,
    db: Any = None,
) -> dict[str, Any]:
    """Process an inbound WhatsApp webhook event.

    Handles:
    - message.received → persist inbound message, create/update memory
    - message.delivered → update message status
    - message.read → update message status
    - message.failed → update message status with error
    """
    result: dict[str, Any] = {
        "event_type": webhook_event.event_type.value,
        "processed": False,
    }

    if db is None:
        result["error"] = "No database session provided"
        return result

    try:
        repo = WhatsAppRepository(db)

        if webhook_event.event_type == WhatsAppWebhookEventType.MESSAGE_RECEIVED:
            # Get or create contact
            sender = webhook_event.sender_number
            contact = repo.get_or_create_contact(
                provider=webhook_event.provider,
                external_id=sender,
                phone_number=sender,
            )

            # Get or create conversation
            conv = repo.get_or_create_conversation(
                provider=webhook_event.provider,
                contact_id=contact.id,
                direction=MessageDirection.INBOUND,
            )

            # Create message record
            msg = repo.create_message(
                conversation_id=conv.id,
                provider=webhook_event.provider,
                direction=MessageDirection.INBOUND,
                content=webhook_event.metadata.get("body", ""),
                external_message_id=webhook_event.external_message_id,
                status=MessageStatus.DELIVERED,
            )
            db.commit()

            # Feed into GoalOS memory
            _feed_memory(
                db=db,
                contact_name=str(contact.name or sender),
                direction="inbound",
                content=webhook_event.metadata.get("body", ""),
                provider=webhook_event.provider,
            )

            result["processed"] = True
            result["message_id"] = msg.id
            result["conversation_id"] = conv.id

        elif webhook_event.event_type in (
            WhatsAppWebhookEventType.MESSAGE_DELIVERED,
            WhatsAppWebhookEventType.MESSAGE_READ,
            WhatsAppWebhookEventType.MESSAGE_FAILED,
            WhatsAppWebhookEventType.MESSAGE_SENT,
        ):
            status_map = {
                WhatsAppWebhookEventType.MESSAGE_SENT: MessageStatus.SENT,
                WhatsAppWebhookEventType.MESSAGE_DELIVERED: MessageStatus.DELIVERED,
                WhatsAppWebhookEventType.MESSAGE_READ: MessageStatus.READ,
                WhatsAppWebhookEventType.MESSAGE_FAILED: MessageStatus.FAILED,
            }
            msg = repo.update_message_status(
                external_message_id=webhook_event.external_message_id,
                status=status_map[webhook_event.event_type],
                provider_status=webhook_event.status,
                error_code=webhook_event.error_code,
                error_message=webhook_event.error_message,
            )
            db.commit()
            result["processed"] = msg is not None
            result["message_id"] = msg.id if msg else None

        else:
            result["error"] = f"Unhandled event type: {webhook_event.event_type.value}"

    except Exception as exc:
        logger.warning("Failed to process WhatsApp webhook: %s", exc)
        result["error"] = str(exc)

    return result


def get_provider_status() -> dict[str, Any]:
    """Return WhatsApp provider status (no secrets)."""
    from app.integrations.whatsapp.factory import get_config_summary, list_available_providers

    provider = _get_provider()
    return {
        "configured": provider is not None and provider.is_configured,
        "available_providers": list_available_providers(),
        "active_provider": provider.name if provider else None,
        "config": get_config_summary() if provider else {},
    }


def get_whatsapp_metrics() -> dict[str, Any]:
    """Return WhatsApp workload metrics for capacity advisor."""
    return {
        "provider": _get_provider().name if _get_provider() else None,
        "configured": _get_provider() is not None and _get_provider().is_configured if _get_provider() else False,
    }


def _feed_memory(
    db: Any,
    contact_name: str,
    direction: str,
    content: str,
    provider: str,
) -> None:
    """Feed a WhatsApp conversation event into the GoalOS memory system.

    Creates a conversation-type memory record that the memory service
    can later recall for "what did we discuss with this customer?"
    queries.
    """
    if not content:
        return
    try:
        from app.db.models.memory import MemoryRecord

        memory = MemoryRecord(
            entity=f"whatsapp:{contact_name}",
            content=f"[WhatsApp {direction}] {content[:500]}",
            memory_type=MemoryType.CONVERSATION,
            importance=0.6,
            confidence=1.0,
            source=f"whatsapp:{provider}",
            metadata_json={
                "channel": "whatsapp",
                "direction": direction,
                "contact": contact_name,
                "provider": provider,
            },
        )
        db.add(memory)
        db.flush()
    except Exception as exc:
        logger.debug("Memory feed skipped: %s", exc)
