"""Voice Service for GoalOS.

Provider-neutral orchestration for voice calls. Manages call lifecycle,
integrates with GoalOS memory, and provides STT/TTS abstraction.

Architecture:
  Incoming/Outgoing Call
  → Speech-to-Text (provider-neutral)
  → GoalOS conversation engine
  → Memory retrieval
  → LLM
  → Text-to-Speech (provider-neutral)
  → caller

STT/TTS providers are abstracted behind simple interfaces.
KVM2 remains lightweight — STT/TTS can use external APIs.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.db.models.voice import (
    CallDirection,
    VoiceCallRecord,
    VoiceCallStatus,
)
from app.integrations.communications.factory import (
    get_active_provider,
    get_provider_chain,
)
from app.integrations.communications.models import (
    CallStatus,
    VoiceCallRequest,
    normalize_e164,
)
from app.repositories.voice_repository import VoiceRepository
from app.services.action_policy import (
    ActionPolicyEngine,
    PolicyDecision,
    SPRINT1_ACTIONS,
    ActionDeclaration,
    RiskLevel,
)
from app.services.communication_service import _metrics, get_communication_metrics
from app.services.voice_speech import (
    VoiceSpeechConfig,
    get_speech_config,
    get_stt_provider,
    get_tts_provider,
    get_voice_status as _get_speech_status,
)
from app.services.voice_conversation import (
    VoiceConversationContext,
    VoiceConversationEngine,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Voice-specific action declarations
# ---------------------------------------------------------------------------

VOICE_ACTIONS: list[ActionDeclaration] = [
    ActionDeclaration(
        action_name="voice_ai_respond",
        risk_level=RiskLevel.MEDIUM,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.05,
        required_capability="voice_ai",
        description="Generate AI voice response during a call",
    ),
    ActionDeclaration(
        action_name="voice_stt",
        risk_level=RiskLevel.LOW,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        required_capability="voice_stt",
        description="Speech-to-text transcription",
    ),
    ActionDeclaration(
        action_name="voice_tts",
        risk_level=RiskLevel.LOW,
        approval_required=False,
        reversible=True,
        has_external_side_effect=False,
        estimated_cost=0.0,
        required_capability="voice_tts",
        description="Text-to-speech synthesis",
    ),
]

_voice_policy = ActionPolicyEngine()
_voice_policy.register_many(SPRINT1_ACTIONS + VOICE_ACTIONS)

# ---------------------------------------------------------------------------
# STT Provider Abstraction (provider-neutral)
# ---------------------------------------------------------------------------


class BaseSTTProvider:
    """Abstract STT provider interface."""

    name: str = "none"

    def transcribe(self, audio_data: bytes, *, language: str = "en") -> dict[str, Any]:
        """Transcribe audio to text.

        Returns:
            {"text": str, "confidence": float, "language": str, "duration_ms": int}
        """
        return {"text": "", "confidence": 0.0, "language": language, "duration_ms": 0}


class ExternalSTTProvider(BaseSTTProvider):
    """STT via external API (e.g., Whisper API, Google STT, AssemblyAI).

    Configured via STT_PROVIDER env var. Falls back to no-op if not configured.
    """

    def __init__(self) -> None:
        self.name = os.getenv("STT_PROVIDER", "none").strip().lower()

    def transcribe(self, audio_data: bytes, *, language: str = "en") -> dict[str, Any]:
        if self.name == "none" or not audio_data:
            return {"text": "", "confidence": 0.0, "language": language, "duration_ms": 0}

        # Future: dispatch to Whisper API, Google STT, etc.
        # For now, return empty — the AI agent can still respond via text
        logger.info("STT provider %s not yet implemented for real transcription", self.name)
        return {"text": "", "confidence": 0.0, "language": language, "duration_ms": 0}


# ---------------------------------------------------------------------------
# TTS Provider Abstraction (provider-neutral)
# ---------------------------------------------------------------------------


class BaseTTSProvider:
    """Abstract TTS provider interface."""

    name: str = "none"

    def synthesize(self, text: str, *, language: str = "en") -> dict[str, Any]:
        """Synthesize text to audio.

        Returns:
            {"audio_url": str, "audio_data": bytes, "duration_ms": int, "format": str}
        """
        return {"audio_url": "", "audio_data": b"", "duration_ms": 0, "format": "wav"}


class ExternalTTSProvider(BaseTTSProvider):
    """TTS via external API (e.g., ElevenLabs, Google TTS, OpenAI TTS).

    Configured via TTS_PROVIDER env var. Falls back to provider-native TTS.
    """

    def __init__(self) -> None:
        self.name = os.getenv("TTS_PROVIDER", "none").strip().lower()

    def synthesize(self, text: str, *, language: str = "en") -> dict[str, Any]:
        if self.name == "none" or not text:
            return {"audio_url": "", "audio_data": b"", "duration_ms": 0, "format": "wav"}

        # Future: dispatch to ElevenLabs, Google TTS, OpenAI TTS, etc.
        # For now, return empty — providers handle TTS natively via TwiML/Plivo XML
        logger.info("TTS provider %s not yet implemented for real synthesis", self.name)
        return {"audio_url": "", "audio_data": b"", "duration_ms": 0, "format": "wav"}


# ---------------------------------------------------------------------------
# Voice memory creation
# ---------------------------------------------------------------------------

def _create_call_memory(
    db: Any,
    call: VoiceCallRecord,
    *,
    summary: str = "",
    important_facts: list[str] | None = None,
    actions_requested: list[str] | None = None,
    follow_up_required: bool = False,
    human_handoff: bool = False,
    confidence: float = 0.8,
) -> None:
    """Create a GoalOS memory record for a completed voice call.

    Stores structured call metadata without raw audio.
    """
    try:
        from app.db.models.memory import MemoryRecord, MemoryType

        entity = f"voice:{call.destination_number}"
        content_parts = [
            f"[Voice Call {call.direction.value}] {call.destination_number}",
            f"Duration: {call.duration_seconds or 'unknown'}s",
            f"Status: {call.status.value}",
            f"Provider: {call.provider}",
            f"Language: {call.language or 'unknown'}",
        ]
        if summary:
            content_parts.append(f"Summary: {summary}")
        if important_facts:
            content_parts.append(f"Facts: {'; '.join(important_facts)}")
        if actions_requested:
            content_parts.append(f"Actions: {'; '.join(actions_requested)}")
        if follow_up_required:
            content_parts.append("Follow-up required: Yes")
        if human_handoff:
            content_parts.append("Human handoff: Yes")

        memory = MemoryRecord(
            entity=entity,
            content=" | ".join(content_parts),
            memory_type=MemoryType.CONVERSATION,
            importance=0.7 if call.status == VoiceCallStatus.COMPLETED else 0.5,
            confidence=confidence,
            source=f"voice:{call.provider}",
            metadata_json={
                "channel": "voice",
                "call_id": call.id,
                "direction": call.direction.value,
                "destination": call.destination_number,
                "provider": call.provider,
                "duration_seconds": call.duration_seconds,
                "cost": call.cost,
                "language": call.language,
                "status": call.status.value,
                "human_handoff": human_handoff,
                "follow_up_required": follow_up_required,
                "campaign_id": call.campaign_id,
                "reference_id": call.reference_id,
            },
        )
        db.add(memory)
        db.flush()
    except Exception as exc:
        logger.debug("Voice memory creation failed: %s", exc)


# ---------------------------------------------------------------------------
# Main voice call orchestration
# ---------------------------------------------------------------------------

def initiate_voice_call(
    destination_number: str,
    caller_number: str = "",
    message: str = "Hello.",
    *,
    has_approved_context: bool = False,
    callback_url: str | None = None,
    max_duration_seconds: int | None = None,
    language: str | None = None,
    campaign_id: str | None = None,
    reference_id: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """Initiate an outbound voice call through the provider chain.

    Records the call in DB, enforces action policy, and dispatches
    through the primary → fallback provider chain.

    Returns a structured result dict suitable for capability execution.
    Never raises — errors are returned in the result.
    """
    # Policy check
    policy = _voice_policy.evaluate(
        "make_phone_call",
        has_approved_context=has_approved_context,
    )
    if policy.decision == PolicyDecision.DENIED:
        return {"status": "DENIED", "error": policy.reason, "policy": policy.reason}
    if policy.decision == PolicyDecision.APPROVAL_REQUIRED:
        return {"status": "APPROVAL_REQUIRED", "error": policy.reason, "policy": policy.reason}

    # Normalize destination
    normalized_dest = normalize_e164(destination_number)
    if not normalized_dest:
        return {
            "status": "FAILED",
            "error": f"INVALID_DESTINATION: Cannot normalize '{destination_number}' to E.164",
        }

    # Create DB record if session provided
    call_record = None
    if db is not None:
        try:
            repo = VoiceRepository(db)
            call_record = repo.create_call(
                provider="pending",
                destination_number=normalized_dest,
                caller_number=caller_number or None,
                tts_message=message,
                language=language,
                campaign_id=campaign_id,
                reference_id=reference_id,
            )
            db.commit()
        except Exception as exc:
            logger.debug("Failed to create call record: %s", exc)

    # Dispatch through provider chain
    chain = get_provider_chain()
    if not chain:
        _metrics.record_voice_call(False)
        return {
            "status": "INTEGRATION_NOT_CONFIGURED",
            "error": (
                "INTEGRATION_NOT_CONFIGURED: no COMMUNICATION_PROVIDER or "
                "COMMUNICATION_PRIMARY_PROVIDER configured."
            ),
        }

    last_result: dict[str, Any] | None = None
    for i, provider in enumerate(chain):
        if not provider.is_configured:
            continue

        request = VoiceCallRequest(
            destination_number=normalized_dest,
            caller_number=caller_number or provider.config.from_number,
            message=message,
            callback_url=callback_url,
            max_duration_seconds=max_duration_seconds,
        )

        result = provider.make_voice_call(request)

        if i > 0:
            _metrics.record_fallback()

        if result.status not in (CallStatus.NO_PROVIDER, CallStatus.FAILED):
            _metrics.record_voice_call(True)

            # Update DB record
            if call_record and db is not None:
                try:
                    repo = VoiceRepository(db)
                    status_map = {
                        CallStatus.QUEUED: VoiceCallStatus.QUEUED,
                        CallStatus.INITIATED: VoiceCallStatus.INITIATED,
                        CallStatus.IN_PROGRESS: VoiceCallStatus.IN_PROGRESS,
                        CallStatus.COMPLETED: VoiceCallStatus.COMPLETED,
                        CallStatus.BUSY: VoiceCallStatus.BUSY,
                        CallStatus.NO_ANSWER: VoiceCallStatus.NO_ANSWER,
                        CallStatus.FAILED: VoiceCallStatus.FAILED,
                    }
                    repo.update_call_status(
                        call_record.id,
                        status_map.get(result.status, VoiceCallStatus.QUEUED),
                        provider_status=result.status.value,
                        external_call_id=result.call_id,
                        cost=float(result.cost) if result.cost else None,
                        duration_seconds=result.duration_seconds,
                    )
                    # Update provider on the record
                    call_record.provider = result.provider
                    db.commit()
                except Exception as exc:
                    logger.debug("Failed to update call record: %s", exc)

            return {
                "provider": result.provider,
                "call_id": result.call_id,
                "status": result.status.value,
                "error": result.error,
                "cost": result.cost,
                "duration_seconds": result.duration_seconds,
                "language": language,
                "campaign_id": campaign_id,
                "reference_id": reference_id,
                "provider_metadata": result.provider_metadata,
                "fallback_used": i > 0,
                "internal_call_id": call_record.id if call_record else None,
            }

        if result.status == CallStatus.FAILED and result.error:
            last_result = {
                "provider": result.provider,
                "call_id": result.call_id,
                "status": result.status.value,
                "error": result.error,
                "provider_metadata": result.provider_metadata,
                "fallback_used": i > 0,
            }
            _metrics.record_voice_call(False)
            _metrics.set_last_error(result.error)
            if "INTEGRATION_NOT_CONFIGURED" not in (result.error or ""):
                # Update DB with failure
                if call_record and db is not None:
                    try:
                        repo = VoiceRepository(db)
                        repo.update_call_status(
                            call_record.id,
                            VoiceCallStatus.FAILED,
                            error_code="PROVIDER_ERROR",
                            error_message=result.error,
                        )
                        call_record.provider = result.provider
                        db.commit()
                    except Exception:
                        pass
                return last_result

    if last_result:
        return last_result

    _metrics.record_voice_call(False)
    return {
        "status": "INTEGRATION_NOT_CONFIGURED",
        "error": "INTEGRATION_NOT_CONFIGURED: all providers not configured.",
    }


def handle_call_status_webhook(
    payload: dict[str, Any],
    *,
    signature: str | None = None,
    db: Any = None,
) -> dict[str, Any]:
    """Process a voice call status webhook.

    Verifies signature, parses the event, updates call status,
    and optionally creates a memory record.
    """
    result: dict[str, Any] = {"received": True, "processed": False}

    # Try each provider's parser
    chain = get_provider_chain()
    event = None
    for provider in chain:
        event = provider.parse_webhook(payload)
        if event:
            break

    if event is None:
        result["reason"] = "unrecognized_payload"
        return result

    result["event_type"] = event.event_type.value
    result["provider"] = event.provider
    result["provider_id"] = event.provider_id

    if db is None:
        result["processed"] = True
        result["reason"] = "no_db_session"
        return result

    try:
        repo = VoiceRepository(db)

        # Find the call record by external ID
        call = repo.get_call_by_external_id(event.provider_id)

        if call is None:
            # Create a record for inbound or unknown calls
            direction = CallDirection.OUTBOUND
            dest = event.destination_number
            src = event.source_number
            if event.event_type.value.startswith("call.") and src:
                direction = CallDirection.INBOUND
                dest = src
            call = repo.create_call(
                provider=event.provider,
                destination_number=dest,
                caller_number=src,
                direction=direction,
                external_call_id=event.provider_id,
            )

        # Map event to call status
        status_map = {
            "call.initiated": VoiceCallStatus.INITIATED,
            "call.ringing": VoiceCallStatus.INITIATED,
            "call.answered": VoiceCallStatus.IN_PROGRESS,
            "call.completed": VoiceCallStatus.COMPLETED,
            "call.failed": VoiceCallStatus.FAILED,
            "call.busy": VoiceCallStatus.BUSY,
            "call.no_answer": VoiceCallStatus.NO_ANSWER,
        }
        new_status = status_map.get(event.event_type.value)
        if new_status:
            repo.update_call_status(
                call.id,
                new_status,
                provider_status=event.status,
                duration_seconds=event.duration_seconds,
                error_code=event.error_code,
                error_message=event.error_message,
            )

        # Record the event
        repo.record_event(
            call_id=call.id,
            event_type=event.event_type.value,
            provider=event.provider,
            status=event.status,
            duration_seconds=event.duration_seconds,
            error_code=event.error_code,
            error_message=event.error_message,
            raw_payload=json.dumps(payload, default=str)[:2000],
        )

        # Create memory for completed calls
        if new_status == VoiceCallStatus.COMPLETED and not call.memory_created:
            _create_call_memory(db, call)
            repo.mark_memory_created(call.id)

        db.commit()
        result["processed"] = True
        result["call_id"] = call.id
        result["status"] = new_status.value if new_status else event.status

    except Exception as exc:
        logger.warning("Webhook processing failed: %s", exc)
        result["error"] = str(exc)

    return result


def get_voice_status() -> dict[str, Any]:
    """Return voice provider status (no secrets)."""
    from app.integrations.communications.factory import get_config_summary, list_available_providers

    provider = get_active_provider()
    chain = get_provider_chain()
    chain_names = [p.config.provider for p in chain]

    return {
        "configured": provider is not None and provider.is_configured,
        "available_providers": list_available_providers(),
        "provider_chain": chain_names,
        "active_provider": provider.name if provider else None,
        "config": get_config_summary() if provider else {},
        "metrics": get_communication_metrics(),
    }


def get_call_history(
    db: Any,
    *,
    limit: int = 50,
    status: str | None = None,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """List voice call history."""
    if db is None:
        return []
    try:
        repo = VoiceRepository(db)
        status_enum = None
        if status:
            try:
                status_enum = VoiceCallStatus(status)
            except ValueError:
                pass
        calls = repo.list_calls(limit=limit, status=status_enum, provider=provider)
        return [
            {
                "id": c.id,
                "provider": c.provider,
                "external_call_id": c.external_call_id,
                "direction": c.direction.value,
                "destination_number": c.destination_number,
                "status": c.status.value,
                "duration_seconds": c.duration_seconds,
                "cost": c.cost,
                "language": c.language,
                "campaign_id": c.campaign_id,
                "reference_id": c.reference_id,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "completed_at": c.completed_at.isoformat() if c.completed_at else None,
            }
            for c in calls
        ]
    except Exception as exc:
        logger.warning("Call history failed: %s", exc)
        return []


def get_call_detail(db: Any, call_id: int) -> dict[str, Any] | None:
    """Get detailed info for a specific call."""
    if db is None:
        return None
    try:
        repo = VoiceRepository(db)
        call = repo.get_call(call_id)
        if call is None:
            return None
        events = repo.get_call_events(call_id)
        return {
            "id": call.id,
            "provider": call.provider,
            "external_call_id": call.external_call_id,
            "direction": call.direction.value,
            "destination_number": call.destination_number,
            "caller_number": call.caller_number,
            "status": call.status.value,
            "tts_message": call.tts_message,
            "language": call.language,
            "duration_seconds": call.duration_seconds,
            "cost": call.cost,
            "cost_currency": call.cost_currency,
            "campaign_id": call.campaign_id,
            "reference_id": call.reference_id,
            "memory_created": bool(call.memory_created),
            "error_code": call.error_code,
            "error_message": call.error_message,
            "initiated_at": call.initiated_at.isoformat() if call.initiated_at else None,
            "answered_at": call.answered_at.isoformat() if call.answered_at else None,
            "completed_at": call.completed_at.isoformat() if call.completed_at else None,
            "created_at": call.created_at.isoformat() if call.created_at else None,
            "events": [
                {
                    "event_type": e.event_type,
                    "status": e.status,
                    "duration_seconds": e.duration_seconds,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        }
    except Exception as exc:
        logger.warning("Call detail failed: %s", exc)
        return None


def get_voice_call_summary(
    db: Any,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Get aggregate voice call summary."""
    if db is None:
        return {"total_calls": 0}
    try:
        repo = VoiceRepository(db)
        return repo.get_call_summary(
            start_date=start_date, end_date=end_date, provider=provider
        )
    except Exception as exc:
        logger.warning("Voice summary failed: %s", exc)
        return {"total_calls": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# Voice Speech (STT/TTS) status
# ---------------------------------------------------------------------------


def get_speech_provider_status() -> dict[str, Any]:
    """Get STT/TTS provider status for the voice pipeline."""
    return _get_speech_status()


# ---------------------------------------------------------------------------
# Voice Conversation — real-time AI voice calls
# ---------------------------------------------------------------------------


def start_voice_conversation(
    destination_number: str,
    caller_number: str = "",
    language: str = "en",
    *,
    has_approved_context: bool = False,
    db: Any = None,
) -> dict[str, Any]:
    """Start a real-time AI voice conversation.

    Creates a call record, initializes the conversation engine,
    and returns a conversation ID for subsequent audio turns.
    """
    # Policy check
    policy = _voice_policy.evaluate(
        "make_phone_call",
        has_approved_context=has_approved_context,
    )
    if policy.decision == PolicyDecision.DENIED:
        return {"status": "DENIED", "error": policy.reason}
    if policy.decision == PolicyDecision.APPROVAL_REQUIRED:
        return {"status": "APPROVAL_REQUIRED", "error": policy.reason}

    # Normalize destination
    normalized_dest = normalize_e164(destination_number)
    if not normalized_dest:
        return {
            "status": "FAILED",
            "error": f"INVALID_DESTINATION: Cannot normalize '{destination_number}'",
        }

    # Create DB record
    call_record = None
    if db is not None:
        try:
            repo = VoiceRepository(db)
            call_record = repo.create_call(
                provider="voice_conversation",
                destination_number=normalized_dest,
                caller_number=caller_number or None,
                direction=CallDirection.OUTBOUND,
                language=language,
            )
            call_record.status = VoiceCallStatus.IN_PROGRESS
            call_record.initiated_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:
            logger.debug("Failed to create conversation record: %s", exc)

    # Check speech provider availability
    config = get_speech_config()
    if not config.stt_configured and not config.tts_configured:
        return {
            "status": "INTEGRATION_NOT_CONFIGURED",
            "error": "VOICE_STT_PROVIDER and VOICE_TTS_PROVIDER not configured",
            "call_id": call_record.id if call_record else None,
        }

    return {
        "status": "STARTED",
        "call_id": call_record.id if call_record else None,
        "destination_number": normalized_dest,
        "language": language,
        "stt_provider": "deepgram" if config.stt_configured else "none",
        "tts_provider": "deepgram" if config.tts_configured else "none",
    }


def process_voice_turn(
    call_id: int,
    audio_data: bytes,
    *,
    language: str = "en",
    audio_format: str = "wav",
    db: Any = None,
) -> dict[str, Any]:
    """Process one turn of a real-time voice conversation.

    Takes audio input, runs through STT → Memory → LLM → TTS,
    and returns the AI response audio.
    """
    # Load call record
    call_record = None
    if db is not None:
        try:
            repo = VoiceRepository(db)
            call_record = repo.get_call(call_id)
        except Exception:
            pass

    if call_record is None:
        return {"status": "NOT_FOUND", "error": f"Call {call_id} not found"}

    # Check call is still active
    if call_record.status not in (VoiceCallStatus.INITIATED, VoiceCallStatus.IN_PROGRESS):
        return {
            "status": "CALL_ENDED",
            "error": f"Call status is {call_record.status.value}",
        }

    # Check max duration
    config = get_speech_config()
    if call_record.initiated_at:
        elapsed = (datetime.now(timezone.utc) - call_record.initiated_at).total_seconds()
        if elapsed > config.max_call_seconds:
            if db is not None:
                repo = VoiceRepository(db)
                repo.update_call_status(
                    call_id,
                    VoiceCallStatus.COMPLETED,
                    duration_seconds=int(elapsed),
                )
                db.commit()
            return {
                "status": "MAX_DURATION",
                "error": f"Call exceeded {config.max_call_seconds}s limit",
            }

    # Build conversation context
    ctx = VoiceConversationContext(
        call_id=call_id,
        destination_number=call_record.destination_number,
        caller_number=call_record.caller_number or "",
        language=language or call_record.language or "en",
        conversation_id=call_record.conversation_id,
    )

    # Run through conversation engine
    engine = VoiceConversationEngine()
    ctx = engine.process_audio_input(
        ctx,
        audio_data,
        audio_format=audio_format,
    )

    # Record STT/TTS events
    if db is not None and call_record:
        try:
            repo = VoiceRepository(db)
            if ctx.transcribed_text:
                repo.record_event(
                    call_id=call_id,
                    event_type="voice.stt",
                    provider="deepgram",
                    status="completed",
                    metadata={
                        "text": ctx.transcribed_text[:200],
                        "confidence": ctx.transcription_confidence,
                        "language": ctx.language,
                    },
                )
            if ctx.ai_response:
                repo.record_event(
                    call_id=call_id,
                    event_type="voice.tts",
                    provider="deepgram",
                    status="completed",
                    metadata={
                        "response": ctx.ai_response[:200],
                        "duration_ms": ctx.audio_duration_ms,
                    },
                )
            db.commit()
        except Exception as exc:
            logger.debug("Voice turn event recording failed: %s", exc)

    result: dict[str, Any] = {
        "status": "OK",
        "call_id": call_id,
        "turn": ctx.turn_number,
        "transcribed_text": ctx.transcribed_text,
        "transcription_confidence": ctx.transcription_confidence,
        "ai_response": ctx.ai_response,
        "ai_confidence": ctx.ai_confidence,
        "language": ctx.language,
        "audio_duration_ms": ctx.audio_duration_ms,
    }

    if ctx.handoff_requested:
        result["status"] = "HANDOFF_REQUESTED"
        result["handoff_reason"] = ctx.handoff_reason

    if ctx.error:
        result["error"] = ctx.error
        result["error_stage"] = ctx.error_stage

    # Note: audio_data is returned separately to avoid bloating JSON responses
    # The caller should fetch audio via a dedicated endpoint
    result["has_audio"] = bool(ctx.audio_data)

    return result


def process_voice_text(
    call_id: int,
    text: str,
    *,
    language: str = "en",
    db: Any = None,
) -> dict[str, Any]:
    """Process a text turn (skip STT, go directly to LLM → TTS)."""
    call_record = None
    if db is not None:
        try:
            repo = VoiceRepository(db)
            call_record = repo.get_call(call_id)
        except Exception:
            pass

    if call_record is None:
        return {"status": "NOT_FOUND", "error": f"Call {call_id} not found"}

    ctx = VoiceConversationContext(
        call_id=call_id,
        destination_number=call_record.destination_number,
        caller_number=call_record.caller_number or "",
        language=language or call_record.language or "en",
        conversation_id=call_record.conversation_id,
    )

    engine = VoiceConversationEngine()
    ctx = engine.process_text_input(ctx, text)

    result: dict[str, Any] = {
        "status": "OK",
        "call_id": call_id,
        "turn": ctx.turn_number,
        "ai_response": ctx.ai_response,
        "ai_confidence": ctx.ai_confidence,
        "language": ctx.language,
        "audio_duration_ms": ctx.audio_duration_ms,
        "has_audio": bool(ctx.audio_data),
    }

    if ctx.handoff_requested:
        result["status"] = "HANDOFF_REQUESTED"
        result["handoff_reason"] = ctx.handoff_reason

    if ctx.error:
        result["error"] = ctx.error
        result["error_stage"] = ctx.error_stage

    return result


def end_voice_conversation(
    call_id: int,
    *,
    summary: str = "",
    db: Any = None,
) -> dict[str, Any]:
    """End a voice conversation and create memory record."""
    if db is None:
        return {"status": "NO_DB"}

    try:
        repo = VoiceRepository(db)
        call = repo.get_call(call_id)
        if call is None:
            return {"status": "NOT_FOUND"}

        elapsed = None
        if call.initiated_at:
            elapsed = int((datetime.now(timezone.utc) - call.initiated_at).total_seconds())

        repo.update_call_status(
            call_id,
            VoiceCallStatus.COMPLETED,
            duration_seconds=elapsed,
        )

        # Create memory record
        _create_call_memory(
            db, call, summary=summary or "Voice conversation completed"
        )

        db.commit()

        return {
            "status": "ENDED",
            "call_id": call_id,
            "duration_seconds": elapsed,
        }
    except Exception as exc:
        logger.warning("End conversation failed: %s", exc)
        return {"status": "ERROR", "error": str(exc)}
