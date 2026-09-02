"""GoalOS WhatsApp AI Auto-Reply Agent.

Processes inbound WhatsApp messages through a complete pipeline:
1. Validate/parse inbound message
2. Idempotency check (deduplicate webhook deliveries)
3. Identify WhatsApp user/contact
4. Retrieve relevant GoalOS memory for this contact
5. Construct AI context (system prompt + memory + conversation)
6. Generate response using the GoalOS LLM abstraction
7. Send response through the existing WhatsApp provider
8. Persist conversation/message/memory metadata

The agent respects the Action Policy:
- Reading/responding is automatic
- Any consequential GoalOS action goes through approval
- WhatsApp messages never bypass approval controls
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.db.models.memory import MemoryType
from app.db.models.whatsapp import (
    HandoffState,
    MessageDirection,
    MessageStatus,
    MediaType,
)
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.services.whatsapp_service import _feed_memory
from app.services.whatsapp_handoff import (
    detect_escalation_trigger,
    request_handoff,
    should_block_ai_reply,
)
from app.services.whatsapp_analytics import (
    track_inbound_message,
    track_outbound_message,
    track_handoff,
)
from app.services.whatsapp_language import (
    augment_prompt_with_language,
    detect_language,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default system prompt for the WhatsApp agent
_DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant for GoalOS, responding via WhatsApp.

Rules:
- Be concise and helpful. WhatsApp messages should be brief.
- You represent a business. Be professional but friendly.
- If you need to perform an action (send email, update CRM, etc.), explain what you would do but do NOT perform it without explicit human approval.
- Never share sensitive business information with unknown contacts.
- If you don't know something, say so honestly.
- Keep responses under 500 characters when possible for WhatsApp readability.
"""

# Maximum context messages to include in LLM prompt
_MAX_CONTEXT_MESSAGES = 10

# Maximum memory records to include
_MAX_MEMORY_RECORDS = 5


def _get_system_prompt() -> str:
    """Return the system prompt, configurable via environment variable."""
    return os.getenv("WHATSAPP_AGENT_SYSTEM_PROMPT", _DEFAULT_SYSTEM_PROMPT)


def _is_auto_reply_enabled() -> bool:
    """Check if auto-reply is enabled via configuration."""
    return os.getenv("WHATSAPP_AUTO_REPLY_ENABLED", "false").strip().lower() in (
        "true", "1", "yes", "on",
    )


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

# In-memory set of recently processed message IDs (bounded, for dedup)
_processed_messages: dict[str, datetime] = {}
_MAX_PROCESSED_CACHE = 10000


def _is_duplicate(message_id: str) -> bool:
    """Check if a message has already been processed (idempotency)."""
    if not message_id:
        return False
    if message_id in _processed_messages:
        return True
    # Evict old entries if cache is full
    if len(_processed_messages) > _MAX_PROCESSED_CACHE:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 3600  # 1 hour
        to_remove = [
            k for k, v in _processed_messages.items()
            if v.timestamp() < cutoff
        ]
        for k in to_remove:
            del _processed_messages[k]
    _processed_messages[message_id] = datetime.now(timezone.utc)
    return False


# ---------------------------------------------------------------------------
# Memory retrieval
# ---------------------------------------------------------------------------

def _retrieve_contact_memory(
    db: Any, contact_entity: str, current_message: str, limit: int = _MAX_MEMORY_RECORDS
) -> list[dict[str, str]]:
    """Retrieve relevant memory for a WhatsApp contact.

    Returns a list of {"role": "user"|"assistant", "content": "..."} dicts
    suitable for LLM context injection.

    Memory isolation: only returns records matching the exact contact entity.
    Never leaks one contact's memory into another's context.
    """
    try:
        from app.db.models.memory import MemoryRecord
        from sqlalchemy import select

        # Search for memories matching this exact contact entity
        stmt = (
            select(MemoryRecord)
            .where(MemoryRecord.entity == contact_entity)
            .order_by(MemoryRecord.created_at.desc())
            .limit(limit)
        )
        records = db.execute(stmt).scalars().all()

        context = []
        for record in reversed(records):  # Chronological order
            content = record.content or ""
            if not content:
                continue
            # Determine if this was inbound or outbound
            direction = "user"
            if record.metadata_json and record.metadata_json.get("direction") == "outbound":
                direction = "assistant"
            context.append({
                "role": direction,
                "content": content,
            })
        return context
    except Exception as exc:
        logger.debug("Memory retrieval failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# LLM response generation
# ---------------------------------------------------------------------------

def _generate_response(
    contact_name: str,
    user_message: str,
    memory_context: list[dict[str, str]],
    system_prompt: str,
) -> str:
    """Generate an AI response using the GoalOS LLM abstraction.

    Builds the prompt from:
    1. System prompt (configurable)
    2. Memory context (recent conversation history)
    3. Current user message

    Returns the generated text, or a fallback message if LLM is unavailable.
    """
    try:
        from app.llm.provider_factory import ProviderFactory
        from app.llm.base_provider import provider_configured

        provider = ProviderFactory.create()
        if not provider_configured(provider):
            logger.info("LLM provider not configured, using fallback response")
            return _fallback_response(contact_name)

        # Build the prompt with context
        prompt_parts = [system_prompt]

        if memory_context:
            prompt_parts.append("\nRecent conversation context:")
            for msg in memory_context[-_MAX_CONTEXT_MESSAGES:]:
                role = "Customer" if msg["role"] == "user" else "Assistant"
                prompt_parts.append(f"{role}: {msg['content'][:200]}")

        prompt_parts.append(f"\nCustomer message: {user_message}")
        prompt_parts.append("\nRespond concisely (under 500 characters):")

        full_prompt = "\n".join(prompt_parts)

        result = provider.request(full_prompt)
        response = result.get("response", "")

        if not response:
            return _fallback_response(contact_name)

        # Truncate to WhatsApp-friendly length
        if len(response) > 1000:
            response = response[:997] + "..."

        return response

    except Exception as exc:
        logger.warning("LLM response generation failed: %s", exc)
        return _fallback_response(contact_name)


def _fallback_response(contact_name: str) -> str:
    """Return a fallback response when LLM is unavailable."""
    return (
        f"Thank you for your message! A team member will respond shortly. "
        f"If this is urgent, please call our support line."
    )


# ---------------------------------------------------------------------------
# Main auto-reply pipeline
# ---------------------------------------------------------------------------

def handle_inbound_message(
    webhook_event: WhatsAppWebhookEvent,
    db: Any,
) -> dict[str, Any]:
    """Process an inbound WhatsApp message through the complete auto-reply pipeline.

    Pipeline:
    1. Idempotency check
    2. Validate message
    3. Persist inbound message
    4. Retrieve contact memory
    5. Generate AI response
    6. Send response via WhatsApp provider
    7. Persist outbound message + memory

    Returns structured result dict.
    """
    result: dict[str, Any] = {
        "event_type": webhook_event.event_type.value,
        "processed": False,
        "auto_replied": False,
    }

    # Only process incoming messages
    if webhook_event.event_type != WhatsAppWebhookEventType.MESSAGE_RECEIVED:
        return result

    message_id = webhook_event.external_message_id
    sender = webhook_event.sender_number
    content = webhook_event.metadata.get("body", "")

    # 1. Idempotency check
    if _is_duplicate(message_id):
        result["processed"] = True
        result["reason"] = "duplicate"
        return result

    # 2. Validate message
    if not sender or not message_id:
        result["error"] = "Invalid webhook: missing sender or message_id"
        return result

    if not content and not webhook_event.metadata.get("media_url"):
        # Non-text message without content — acknowledge but don't auto-reply
        result["processed"] = True
        result["reason"] = "non_text_message"
        return result

    # Check if auto-reply is enabled
    if not _is_auto_reply_enabled():
        result["processed"] = True
        result["reason"] = "auto_reply_disabled"
        return result

    try:
        repo = WhatsAppRepository(db)

        # 3. Persist inbound message
        contact = repo.get_or_create_contact(
            provider=webhook_event.provider,
            external_id=sender,
            phone_number=sender,
        )
        conv = repo.get_or_create_conversation(
            provider=webhook_event.provider,
            contact_id=contact.id,
            direction=MessageDirection.INBOUND,
        )
        inbound_msg = repo.create_message(
            conversation_id=conv.id,
            provider=webhook_event.provider,
            direction=MessageDirection.INBOUND,
            content=content,
            external_message_id=message_id,
            status=MessageStatus.DELIVERED,
        )
        db.commit()

        # Feed inbound into memory
        contact_entity = f"whatsapp:{contact.name or sender}"
        _feed_memory(
            db=db,
            contact_name=str(contact.name or sender),
            direction="inbound",
            content=content,
            provider=webhook_event.provider,
        )

        # Track analytics — inbound message
        track_inbound_message(
            db=db,
            conversation_id=conv.id,
            contact_id=contact.id,
            provider=webhook_event.provider,
        )

        # Detect language
        lang_result = detect_language(content)
        detected_lang = lang_result["language"]
        if detected_lang != "unknown":
            from app.services.whatsapp_analytics import set_language
            set_language(db=db, conversation_id=conv.id, language=detected_lang)

        # 4. Check if human handoff is active
        if should_block_ai_reply(db, conv.id):
            result["processed"] = True
            result["auto_replied"] = False
            result["reason"] = "human_handoff_active"
            result["conversation_id"] = conv.id
            result["contact_id"] = contact.id
            return result

        # 5. Detect escalation triggers
        escalation = detect_escalation_trigger(
            content=content,
            conversation_id=conv.id,
        )
        if escalation["should_escalate"]:
            handoff_result = request_handoff(
                db=db,
                conversation_id=conv.id,
                reason=escalation["reason"],
                detail=escalation["detail"],
            )
            # Track handoff analytics
            track_handoff(db=db, conversation_id=conv.id, reason=escalation["reason"])
            # Send a brief acknowledgment to the customer
            ack_text = (
                "Thank you for your message. I'm connecting you with a team "
                "member who can help you further. They'll be with you shortly."
            )
            from app.services.whatsapp_service import send_message

            send_result = send_message(
                destination_number=sender,
                message=ack_text,
                has_approved_context=True,
                db=db,
            )
            result["processed"] = True
            result["auto_replied"] = send_result.get("status") in ("sent", "queued")
            result["escalated"] = True
            result["escalation_reason"] = escalation["reason"]
            result["handoff_status"] = handoff_result.get("status")
            result["conversation_id"] = conv.id
            result["contact_id"] = contact.id
            return result

        # 6. Retrieve contact memory
        memory_context = _retrieve_contact_memory(db, contact_entity, content)

        # 7. Generate AI response (with language augmentation)
        system_prompt = _get_system_prompt()
        if detected_lang != "unknown":
            system_prompt = augment_prompt_with_language(system_prompt, detected_lang)
        response_text = _generate_response(
            contact_name=str(contact.name or sender),
            user_message=content,
            memory_context=memory_context,
            system_prompt=system_prompt,
        )

        # 8. Send response via WhatsApp provider
        from app.services.whatsapp_service import send_message

        send_result = send_message(
            destination_number=sender,
            message=response_text,
            has_approved_context=True,  # Auto-reply is pre-authorized
            db=db,
        )

        # 9. Track analytics — outbound AI response
        is_success = send_result.get("status") in ("sent", "queued")
        track_outbound_message(
            db=db,
            conversation_id=conv.id,
            contact_id=contact.id,
            provider=webhook_event.provider,
            is_ai_response=True,
            is_failed=not is_success,
        )

        # 10. Result
        result["processed"] = True
        result["auto_replied"] = is_success
        result["inbound_message_id"] = inbound_msg.id
        result["conversation_id"] = conv.id
        result["contact_id"] = contact.id
        result["response_status"] = send_result.get("status")
        result["response_message_id"] = send_result.get("external_message_id")
        result["detected_language"] = detected_lang

        if send_result.get("error"):
            result["send_error"] = send_result["error"]

        return result

    except Exception as exc:
        logger.warning("Auto-reply pipeline failed: %s", exc)
        result["error"] = str(exc)
        return result


# ---------------------------------------------------------------------------
# Configuration/status
# ---------------------------------------------------------------------------

def get_agent_status() -> dict[str, Any]:
    """Return WhatsApp agent configuration status (no secrets)."""
    from app.llm.provider_factory import ProviderFactory
    from app.llm.base_provider import provider_configured

    llm_configured = False
    llm_provider = None
    try:
        provider = ProviderFactory.create()
        llm_configured = provider_configured(provider)
        llm_provider = type(provider).__name__
    except Exception:
        pass

    return {
        "auto_reply_enabled": _is_auto_reply_enabled(),
        "llm_configured": llm_configured,
        "llm_provider": llm_provider,
        "system_prompt_length": len(_get_system_prompt()),
        "recent_messages_cached": len(_processed_messages),
    }
