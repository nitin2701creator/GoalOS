"""Provider-neutral WhatsApp models for GoalOS.

Request/response models that abstract away provider-specific details.
Secrets are never included in these models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WhatsAppStatus(str, Enum):
    """Outcome of a WhatsApp operation."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    NO_PROVIDER = "no_provider"


class WhatsAppMediaType(str, Enum):
    """Supported media types."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    CONTACT = "contact"
    STICKER = "sticker"


class WhatsAppWebhookEventType(str, Enum):
    """Webhook event types for message lifecycle."""

    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    MESSAGE_DELIVERED = "message.delivered"
    MESSAGE_READ = "message.read"
    MESSAGE_FAILED = "message.failed"
    CONTACT_UPDATE = "contact.update"
    PRESENCE_UPDATE = "presence.update"


# ---------------------------------------------------------------------------
# E.164 phone number normalization (reuse from communications)
# ---------------------------------------------------------------------------

_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_e164(number: str, default_country_code: str = "1") -> str:
    """Normalize a phone number to E.164 format."""
    from app.integrations.communications.models import normalize_e164 as _norm

    return _norm(number, default_country_code)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendMessageRequest:
    """Provider-neutral outbound WhatsApp message request.

    Attributes:
        destination_number: E.164 formatted destination (+1234567890).
        message: Text message body.
        media_url: URL of media attachment (image/video/audio/document).
        media_type: Type of media if sending media.
        caption: Caption for media messages.
        callback_url: Webhook URL for delivery status updates.
        metadata: Arbitrary metadata attached to the message.
    """

    destination_number: str
    message: str = ""
    media_url: str | None = None
    media_type: WhatsAppMediaType = WhatsAppMediaType.TEXT
    caption: str | None = None
    callback_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReceiveMessageRequest:
    """Parsed inbound WhatsApp message from webhook.

    Attributes:
        provider: Provider name.
        external_message_id: Provider-assigned message ID.
        sender_number: E.164 formatted sender.
        message: Text content.
        media_url: URL of media attachment.
        media_type: Type of media.
        timestamp: Provider timestamp.
        metadata: Raw provider payload.
    """

    provider: str
    external_message_id: str
    sender_number: str
    message: str = ""
    media_url: str | None = None
    media_type: WhatsAppMediaType = WhatsAppMediaType.TEXT
    timestamp: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendMessageResponse:
    """Result of an outbound WhatsApp message attempt.

    Attributes:
        provider: Provider name.
        external_message_id: Provider-assigned message ID.
        status: Current delivery status.
        error: Error message if failed.
        provider_metadata: Raw provider response fields.
    """

    provider: str
    external_message_id: str | None = None
    status: WhatsAppStatus = WhatsAppStatus.QUEUED
    error: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WhatsAppWebhookEvent:
    """A parsed provider webhook event.

    Adapters parse provider-specific webhook payloads into this
    normalized representation.
    """

    event_type: WhatsAppWebhookEventType
    provider: str
    external_message_id: str
    status: str
    sender_number: str = ""
    destination_number: str = ""
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Template Message models
# ---------------------------------------------------------------------------


class TemplateComponentType(str, Enum):
    """Template component types."""

    HEADER = "header"
    BODY = "body"
    BUTTON = "button"


class TemplateParameterType(str, Enum):
    """Parameter types for template components."""

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    CURRENCY = "currency"
    DATE_TIME = "date_time"
    PAYLOAD = "payload"


class TemplateStatus(str, Enum):
    """Status of a template send operation."""

    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    REJECTED = "rejected"
    NO_PROVIDER = "no_provider"
    INVALID_TEMPLATE = "invalid_template"


@dataclass(frozen=True, slots=True)
class TemplateParameter:
    """A single parameter within a template component."""

    type: TemplateParameterType
    text: str | None = None
    image_url: str | None = None
    video_url: str | None = None
    document_url: str | None = None
    currency_code: str | None = None
    currency_amount: str | None = None
    fallback_value: str | None = None
    payload: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateComponent:
    """A component (header/body/button) of a template message."""

    type: TemplateComponentType
    sub_type: str | None = None  # button sub_type: quick_reply, url
    index: int | None = None  # button index
    parameters: list[TemplateParameter] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SendTemplateRequest:
    """Provider-neutral template message request.

    Represents a WhatsApp template message that can be sent through
    any provider adapter.

    Attributes:
        template_name: Name of the approved Meta template.
        language_code: Language code (e.g., 'en', 'en_US', 'hi').
        recipient_number: E.164 formatted destination.
        components: Template components (header, body, button).
        correlation_id: Optional correlation ID for tracking.
        callback_url: Webhook URL for delivery status.
        metadata: Arbitrary metadata.
    """

    template_name: str
    language_code: str
    recipient_number: str
    components: list[TemplateComponent] = field(default_factory=list)
    correlation_id: str | None = None
    callback_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SendTemplateResponse:
    """Result of a template message send attempt."""

    provider: str
    external_message_id: str | None = None
    status: TemplateStatus = TemplateStatus.QUEUED
    error: str | None = None
    correlation_id: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TemplateDefinition:
    """A configurable template definition in GoalOS.

    Templates are pre-approved by Meta and defined by the business.
    This model stores the metadata for template management.
    """

    name: str
    language_code: str
    category: str  # marketing, transactional, utility, authentication
    description: str = ""
    header_type: str | None = None  # text, image, video, document, None
    body_text: str = ""
    buttons: list[dict[str, str]] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    status: str = "approved"  # approved, pending, rejected
    example_values: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def redact_whatsapp_config(config: dict[str, Any]) -> dict[str, str]:
    """Return a mapping where every secret value is masked."""
    from app.integrations.communications.models import redact_credentials

    return redact_credentials(config)
