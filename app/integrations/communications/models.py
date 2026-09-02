"""Provider-neutral communication models for GoalOS.

Request/response models for voice calls and SMS that abstract away
provider-specific details. Secrets are never included in these models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# E.164 phone number normalization
# ---------------------------------------------------------------------------

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_e164(number: str, default_country_code: str = "1") -> str:
    """Normalize a phone number to E.164 format.

    Accepts:
        +15551234567  → +15551234567  (already E.164)
        15551234567   → +15551234567  (US without +)
        5551234567    → +15551234567  (US local, prepend +1)
        +919876543210 → +919876543210 (India, already E.164)
        09876543210   → +919876543210 (India local, best-effort)

    Returns empty string if the number cannot be normalized.
    """
    cleaned = number.strip()
    if not cleaned:
        return ""
    # Remove spaces, dashes, parentheses
    cleaned = re.sub(r"[\s\-\(\)]", "", cleaned)
    # Already E.164
    if cleaned.startswith("+") and _E164_RE.match(cleaned):
        return cleaned
    # Digits only — try to construct E.164
    digits = re.sub(r"[^\d]", "", cleaned)
    if not digits:
        return ""
    # US/Canada: 10 digits without country code
    if len(digits) == 10 and default_country_code == "1":
        candidate = f"+1{digits}"
        if _E164_RE.match(candidate):
            return candidate
    # With country code
    if len(digits) >= 8:
        candidate = f"+{digits}"
        if _E164_RE.match(candidate):
            return candidate
    # Try prepending default country code
    candidate = f"+{default_country_code}{digits}"
    if _E164_RE.match(candidate):
        return candidate
    return ""


def is_valid_e164(number: str) -> bool:
    """Check if a number is valid E.164 format."""
    return bool(_E164_RE.match(number.strip()))


class CommunicationStatus(str, Enum):
    """Outcome of a communication operation."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    NO_PROVIDER = "no_provider"


class CallStatus(str, Enum):
    """Outcome of a voice call."""

    QUEUED = "queued"
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    NO_PROVIDER = "no_provider"


# ---------------------------------------------------------------------------
# Voice call models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class VoiceCallRequest:
    """Provider-neutral outbound voice call request.

    Attributes:
        destination_number: E.164 formatted destination (+1234567890).
        caller_number: E.164 formatted caller/agent number.
        message: Text-to-speech message for the call.
        max_duration_seconds: Maximum call duration (provider default if None).
        callback_url: Webhook URL for call status updates.
        metadata: Arbitrary metadata attached to the call.
    """

    destination_number: str
    caller_number: str
    message: str
    max_duration_seconds: int | None = None
    callback_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VoiceCallResponse:
    """Result of an outbound voice call attempt.

    Attributes:
        provider: Provider name (e.g. "twilio", "plivo").
        call_id: Provider-assigned call/message ID.
        status: Current call status.
        error: Error message if failed.
        cost: Estimated cost in provider currency units (None if unknown).
        duration_seconds: Call duration if completed (None if not yet).
        provider_metadata: Raw provider response fields.
    """

    provider: str
    call_id: str | None = None
    status: CallStatus = CallStatus.QUEUED
    error: str | None = None
    cost: str | None = None
    duration_seconds: int | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SMS models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SmsRequest:
    """Provider-neutral outbound SMS request.

    Attributes:
        destination_number: E.164 formatted destination (+1234567890).
        sender_number: E.164 formatted sender/agent number.
        message: SMS body text.
        callback_url: Webhook URL for delivery status updates.
        metadata: Arbitrary metadata attached to the message.
    """

    destination_number: str
    sender_number: str
    message: str
    callback_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SmsResponse:
    """Result of an outbound SMS attempt.

    Attributes:
        provider: Provider name (e.g. "twilio", "plivo").
        message_id: Provider-assigned message ID.
        status: Current delivery status.
        error: Error message if failed.
        cost: Estimated cost in provider currency units (None if unknown).
        provider_metadata: Raw provider response fields.
    """

    provider: str
    message_id: str | None = None
    status: CommunicationStatus = CommunicationStatus.QUEUED
    error: str | None = None
    cost: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Redacted representation helpers (secrets never leave the system)
# ---------------------------------------------------------------------------

def redact_credentials(config: dict[str, Any]) -> dict[str, str]:
    """Return a mapping where every secret value is masked.

    Used when communicating provider configuration state without
    exposing actual credentials through API responses or logs.
    """
    result: dict[str, str] = {}
    for key, value in config.items():
        if value is None or value == "":
            result[key] = ""
        else:
            s = str(value)
            if len(s) > 8:
                result[key] = s[:3] + "****" + s[-3:]
            else:
                result[key] = "****"
    return result


# ---------------------------------------------------------------------------
# Webhook / status event models (foundation for call/SMS lifecycle)
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """Types of communication lifecycle events."""

    # Voice call events
    CALL_INITIATED = "call.initiated"
    CALL_RINGING = "call.ringing"
    CALL_ANSWERED = "call.answered"
    CALL_COMPLETED = "call.completed"
    CALL_FAILED = "call.failed"
    CALL_BUSY = "call.busy"
    CALL_NO_ANSWER = "call.no_answer"
    # SMS events
    SMS_QUEUED = "sms.queued"
    SMS_SENT = "sms.sent"
    SMS_DELIVERED = "sms.delivered"
    SMS_FAILED = "sms.failed"


@dataclass(frozen=True, slots=True)
class StatusEvent:
    """A provider webhook/status callback event.

    Adapters parse provider-specific webhook payloads into this
    normalized representation for logging, auditing, and downstream
    event handling.
    """

    event_type: EventType
    provider: str
    provider_id: str  # provider-assigned call SID or message UUID
    status: str  # raw provider status string
    destination_number: str = ""
    source_number: str = ""
    duration_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cost: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
