"""Communication API endpoints.

POST /api/v1/communications/voice-call  — initiate an outbound voice call.
POST /api/v1/communications/sms         — send an outbound SMS.
GET  /api/v1/communications/status     — provider status and config summary.
POST /api/v1/communications/webhook    — receive provider status callbacks.
GET  /api/v1/communications/metrics    — communication workload metrics.
GET  /api/v1/communications/voice/status — voice-specific status.
GET  /api/v1/communications/voice/history — call history.
GET  /api/v1/communications/voice/calls/{id} — call detail.
GET  /api/v1/communications/voice/summary — aggregate call summary.
POST /api/v1/communications/voice/webhook — voice-specific webhook.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.communications.factory import (
    get_config_summary,
    is_configured,
    list_available_providers,
    get_provider_chain,
)
from app.services.communication_service import (
    make_voice_call,
    send_sms,
    get_communication_metrics,
)
from app.services.voice_service import (
    get_voice_status,
    get_call_history,
    get_call_detail,
    get_voice_call_summary,
    handle_call_status_webhook,
    initiate_voice_call as voice_initiate,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class VoiceCallRequest(BaseModel):
    """Request to initiate a voice call."""

    destination_number: str = Field(min_length=1, description="E.164 destination number (+1234567890)")
    caller_number: str = Field(default="", description="E.164 caller number (uses provider default if empty)")
    message: str = Field(min_length=1, description="Text-to-speech message")
    approved: bool = Field(default=False, description="Whether the call has been pre-approved by an operator")
    callback_url: str | None = Field(default=None, description="Webhook URL for call status updates")
    max_duration_seconds: int | None = Field(default=None, description="Maximum call duration in seconds")
    language: str | None = Field(default=None, description="Language code for TTS (e.g. 'en', 'hi')")
    campaign_id: str | None = Field(default=None, description="Campaign reference ID")
    reference_id: str | None = Field(default=None, description="Custom reference ID")


class SmsRequest(BaseModel):
    """Request to send an SMS."""

    destination_number: str = Field(min_length=1, description="E.164 destination number (+1234567890)")
    sender_number: str = Field(default="", description="E.164 sender number (uses provider default if empty)")
    message: str = Field(min_length=1, description="SMS body text")
    approved: bool = Field(default=False, description="Whether the SMS has been pre-approved by an operator")
    callback_url: str | None = Field(default=None, description="Webhook URL for delivery status updates")


# ---------------------------------------------------------------------------
# Core communication endpoints
# ---------------------------------------------------------------------------

@router.get("/status")
def communication_status():
    """Return provider configuration status (no secrets exposed)."""
    configured = is_configured()
    providers = list_available_providers()
    summary = get_config_summary()
    chain = get_provider_chain()
    chain_names = [p.config.provider for p in chain]
    return {
        "configured": configured,
        "available_providers": providers,
        "provider_chain": chain_names,
        "active": summary,
    }


@router.post("/voice-call")
def initiate_voice_call_endpoint(request: VoiceCallRequest, db: Session = Depends(get_db)):
    """Initiate an outbound voice call through the active provider chain."""
    result = voice_initiate(
        destination_number=request.destination_number,
        caller_number=request.caller_number,
        message=request.message,
        has_approved_context=request.approved,
        callback_url=request.callback_url,
        max_duration_seconds=request.max_duration_seconds,
        language=request.language,
        campaign_id=request.campaign_id,
        reference_id=request.reference_id,
        db=db,
    )
    return result


@router.post("/sms")
def send_sms_endpoint(request: SmsRequest):
    """Send an outbound SMS through the active provider chain."""
    result = send_sms(
        destination_number=request.destination_number,
        sender_number=request.sender_number,
        message=request.message,
        has_approved_context=request.approved,
        callback_url=request.callback_url,
    )
    return result


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive a provider status callback webhook.

    Processes the webhook through voice_service for call status tracking
    and memory creation.
    """
    form_data = await request.form()
    payload = {k: v for k, v in form_data.items()}

    # Also try JSON body
    if not payload:
        try:
            import json
            body = await request.body()
            payload = json.loads(body.decode())
        except Exception:
            payload = {}

    result = handle_call_status_webhook(payload, db=db)
    return result


@router.get("/metrics")
def communication_metrics():
    """Return communication workload metrics for capacity advisor."""
    return get_communication_metrics()


# ---------------------------------------------------------------------------
# Voice-specific endpoints
# ---------------------------------------------------------------------------

@router.get("/voice/status")
def voice_status():
    """Return voice-specific provider status and metrics."""
    return get_voice_status()


@router.get("/voice/history")
def voice_call_history(
    limit: int = 50,
    status: str | None = None,
    provider: str | None = None,
    db: Session = Depends(get_db),
):
    """List voice call history with optional filters."""
    return {
        "calls": get_call_history(db, limit=limit, status=status, provider=provider),
    }


@router.get("/voice/calls/{call_id}")
def voice_call_detail(call_id: int, db: Session = Depends(get_db)):
    """Get detailed info for a specific voice call."""
    result = get_call_detail(db, call_id)
    if result is None:
        return {"error": "Call not found"}
    return result


@router.get("/voice/summary")
def voice_call_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    provider: str | None = None,
    db: Session = Depends(get_db),
):
    """Get aggregate voice call summary with date-range filtering."""
    from datetime import datetime as dt
    start = dt.fromisoformat(start_date) if start_date else None
    end = dt.fromisoformat(end_date) if end_date else None
    return get_voice_call_summary(db, start_date=start, end_date=end, provider=provider)


# ---------------------------------------------------------------------------
# Voice Speech (STT/TTS) status
# ---------------------------------------------------------------------------


class VoiceSpeechStatusResponse(BaseModel):
    """Response for voice speech provider status."""
    stt: dict[str, Any] = {}
    tts: dict[str, Any] = {}
    config: dict[str, Any] = {}


@router.get("/voice/speech/status")
def voice_speech_status():
    """Get STT/TTS provider status."""
    from app.services.voice_service import get_speech_provider_status
    return get_speech_provider_status()


# ---------------------------------------------------------------------------
# Voice Conversation — real-time AI voice calls
# ---------------------------------------------------------------------------


class VoiceConversationStartRequest(BaseModel):
    """Request to start a real-time voice conversation."""
    destination_number: str = Field(min_length=1, description="E.164 destination number")
    caller_number: str = Field(default="", description="E.164 caller number")
    language: str = Field(default="en", description="Language code")
    approved: bool = Field(default=False, description="Pre-approved by operator")


class VoiceConversationTurnRequest(BaseModel):
    """Request to process one turn of a voice conversation."""
    call_id: int = Field(description="Call ID from start")
    language: str = Field(default="en", description="Language code")
    audio_format: str = Field(default="wav", description="Audio format")


class VoiceConversationTextRequest(BaseModel):
    """Request to process a text turn in voice conversation."""
    call_id: int = Field(description="Call ID from start")
    text: str = Field(min_length=1, description="Text input")
    language: str = Field(default="en", description="Language code")


class VoiceConversationEndRequest(BaseModel):
    """Request to end a voice conversation."""
    call_id: int = Field(description="Call ID to end")
    summary: str = Field(default="", description="Optional summary")


@router.post("/voice/conversation/start")
def voice_conversation_start(
    request: VoiceConversationStartRequest,
    db: Session = Depends(get_db),
):
    """Start a real-time AI voice conversation."""
    from app.services.voice_service import start_voice_conversation
    return start_voice_conversation(
        destination_number=request.destination_number,
        caller_number=request.caller_number,
        language=request.language,
        has_approved_context=request.approved,
        db=db,
    )


@router.post("/voice/conversation/turn")
def voice_conversation_turn(
    request: VoiceConversationTurnRequest,
    db: Session = Depends(get_db),
):
    """Process one turn of audio input in a voice conversation."""
    from app.services.voice_service import process_voice_turn
    # Audio data would come from multipart form in production
    # For API testing, we accept empty audio and process text-only
    return process_voice_turn(
        call_id=request.call_id,
        audio_data=b"",
        language=request.language,
        audio_format=request.audio_format,
        db=db,
    )


@router.post("/voice/conversation/text")
def voice_conversation_text(
    request: VoiceConversationTextRequest,
    db: Session = Depends(get_db),
):
    """Process a text turn in a voice conversation (skip STT)."""
    from app.services.voice_service import process_voice_text
    return process_voice_text(
        call_id=request.call_id,
        text=request.text,
        language=request.language,
        db=db,
    )


@router.post("/voice/conversation/end")
def voice_conversation_end(
    request: VoiceConversationEndRequest,
    db: Session = Depends(get_db),
):
    """End a voice conversation and create memory record."""
    from app.services.voice_service import end_voice_conversation
    return end_voice_conversation(
        call_id=request.call_id,
        summary=request.summary,
        db=db,
    )
