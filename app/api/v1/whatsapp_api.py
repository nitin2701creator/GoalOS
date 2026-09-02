"""WhatsApp API endpoints for GoalOS.

POST /api/v1/whatsapp/send           — send an outbound WhatsApp message.
POST /api/v1/whatsapp/webhook        — receive provider webhook events.
GET  /api/v1/whatsapp/status         — provider status and config summary.
GET  /api/v1/whatsapp/contacts       — list WhatsApp contacts.
GET  /api/v1/whatsapp/conversations   — list conversations.
GET  /api/v1/whatsapp/conversations/{id}/messages — list messages.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.integrations.whatsapp.factory import (
    get_active_provider,
    get_config_summary,
    is_configured,
    list_available_providers,
)
from app.integrations.whatsapp.models import (
    SendMessageRequest as ProviderMessageRequest,
    WhatsAppMediaType,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.db.models.whatsapp import HandoffState
from app.services.whatsapp_service import (
    get_provider_status,
    process_inbound,
    send_message,
)
from app.services.whatsapp_agent import get_agent_status, handle_inbound_message
from app.services.whatsapp_handoff import (
    activate_human_handling,
    get_handoff_context,
    get_pending_handoffs,
    request_handoff,
    resolve_handoff,
    return_to_ai,
)
from app.integrations.whatsapp.models import (
    SendTemplateRequest,
    TemplateComponent,
    TemplateComponentType,
    TemplateParameter,
    TemplateParameterType,
)
from app.services.whatsapp_templates import (
    get_template,
    list_templates,
    preview_template_payload,
    send_template_message,
    validate_template_request,
)
from app.services.whatsapp_analytics import (
    get_analytics_summary,
    get_conversation_analytics,
    list_conversation_analytics,
)

router = APIRouter()


class SendMessageAPIRequest(BaseModel):
    """Request to send a WhatsApp message."""

    destination_number: str = Field(min_length=1, description="E.164 destination number (+1234567890)")
    message: str = Field(default="", description="Text message body")
    media_url: str | None = Field(default=None, description="URL of media attachment")
    media_type: str = Field(default="text", description="Media type: text, image, video, audio, document")
    caption: str | None = Field(default=None, description="Caption for media messages")
    approved: bool = Field(default=False, description="Pre-approved by operator")


@router.get("/status")
def whatsapp_status():
    """Return WhatsApp provider configuration status (no secrets exposed)."""
    return get_provider_status()


@router.get("/agent/status")
def whatsapp_agent_status():
    """Return WhatsApp auto-reply agent configuration status."""
    return get_agent_status()


@router.post("/send")
def send_whatsapp_message(request: SendMessageAPIRequest):
    """Send an outbound WhatsApp message through the active provider."""
    media_type_map = {
        "text": WhatsAppMediaType.TEXT,
        "image": WhatsAppMediaType.IMAGE,
        "video": WhatsAppMediaType.VIDEO,
        "audio": WhatsAppMediaType.AUDIO,
        "document": WhatsAppMediaType.DOCUMENT,
    }
    result = send_message(
        destination_number=request.destination_number,
        message=request.message,
        media_url=request.media_url,
        media_type=media_type_map.get(request.media_type, WhatsAppMediaType.TEXT),
        caption=request.caption,
        has_approved_context=request.approved,
    )
    return result


@router.post("/webhook")
async def receive_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive a WhatsApp provider webhook event.

    Parses the webhook payload using the active provider's adapter,
    validates the signature, and processes the event.
    """
    body = await request.body()
    form_data = await request.form()
    payload = {k: v for k, v in form_data.items()}

    # Also try JSON body
    if not payload:
        try:
            import json
            payload = json.loads(body.decode())
        except Exception:
            payload = {}

    # Verify webhook signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    provider = get_active_provider()
    if provider and not provider.verify_webhook(body, signature):
        return {"received": False, "error": "Invalid webhook signature"}

    # Parse with provider adapter
    event: WhatsAppWebhookEvent | None = None
    if provider:
        event = provider.parse_webhook(payload)

    if event is None:
        return {"received": True, "processed": False, "reason": "unrecognized payload"}

    # Process the event — try auto-reply first, fall back to basic processing
    from app.services.whatsapp_agent import _is_auto_reply_enabled
    if _is_auto_reply_enabled() and event.event_type == WhatsAppWebhookEventType.MESSAGE_RECEIVED:
        result = handle_inbound_message(event, db=db)
    else:
        result = process_inbound(event, db=db)
    result["received"] = True
    return result


@router.get("/contacts")
def list_contacts(
    provider: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List WhatsApp contacts."""
    repo = WhatsAppRepository(db)
    contacts = repo.list_contacts(provider=provider, limit=limit)
    return {
        "contacts": [
            {
                "id": c.id,
                "provider": c.provider,
                "external_id": c.external_id,
                "phone_number": c.phone_number,
                "name": c.name,
                "is_business": c.is_business,
                "last_seen_at": c.last_seen_at.isoformat() if c.last_seen_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in contacts
        ],
        "total": len(contacts),
    }


@router.get("/conversations")
def list_conversations(
    contact_id: int | None = None,
    active_only: bool = True,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List WhatsApp conversations."""
    repo = WhatsAppRepository(db)
    convs = repo.list_conversations(
        contact_id=contact_id, active_only=active_only, limit=limit
    )
    return {
        "conversations": [
            {
                "id": c.id,
                "provider": c.provider,
                "contact_id": c.contact_id,
                "direction": c.direction.value,
                "message_count": c.message_count,
                "is_active": c.is_active,
                "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in convs
        ],
        "total": len(convs),
    }


@router.get("/conversations/{conversation_id}/messages")
def list_messages(
    conversation_id: int,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """List messages in a conversation."""
    repo = WhatsAppRepository(db)
    conv = repo.get_conversation(conversation_id)
    if conv is None:
        return {"error": "Conversation not found", "messages": []}
    messages = repo.list_messages(conversation_id=conversation_id, limit=limit)
    return {
        "conversation_id": conversation_id,
        "messages": [
            {
                "id": m.id,
                "provider": m.provider,
                "direction": m.direction.value,
                "media_type": m.media_type.value,
                "content": m.content,
                "status": m.status.value,
                "external_message_id": m.external_message_id,
                "sent_at": m.sent_at.isoformat() if m.sent_at else None,
                "delivered_at": m.delivered_at.isoformat() if m.delivered_at else None,
                "read_at": m.read_at.isoformat() if m.read_at else None,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "total": len(messages),
    }


# ---------------------------------------------------------------------------
# Template endpoints
# ---------------------------------------------------------------------------


@router.get("/templates")
def list_whatsapp_templates():
    """List all configured WhatsApp template definitions."""
    return {
        "templates": list_templates(),
        "total": len(list_templates()),
    }


@router.get("/templates/{template_name}")
def get_whatsapp_template(template_name: str):
    """Get a specific template definition by name."""
    template = get_template(template_name)
    if template is None:
        return {"error": f"Template '{template_name}' not found"}
    return template


@router.post("/templates/validate")
def validate_whatsapp_template(request: SendTemplateAPIRequest):
    """Validate a template request without sending."""
    components = []
    for comp_dict in request.components:
        params = []
        for p in comp_dict.get("parameters", []):
            params.append(TemplateParameter(
                type=TemplateParameterType(p.get("type", "text")),
                text=p.get("text"),
                image_url=p.get("image_url"),
                video_url=p.get("video_url"),
                document_url=p.get("document_url"),
                payload=p.get("payload"),
            ))
        components.append(TemplateComponent(
            type=TemplateComponentType(comp_dict.get("type", "body")),
            sub_type=comp_dict.get("sub_type"),
            index=comp_dict.get("index"),
            parameters=params,
        ))

    template_req = SendTemplateRequest(
        template_name=request.template_name,
        language_code=request.language_code,
        recipient_number=request.recipient_number,
        components=components,
        correlation_id=request.correlation_id,
    )
    return validate_template_request(template_req)


@router.post("/templates/preview")
def preview_whatsapp_template(request: SendTemplateAPIRequest):
    """Preview a template payload without sending."""
    components = []
    for comp_dict in request.components:
        params = []
        for p in comp_dict.get("parameters", []):
            params.append(TemplateParameter(
                type=TemplateParameterType(p.get("type", "text")),
                text=p.get("text"),
                image_url=p.get("image_url"),
                video_url=p.get("video_url"),
                document_url=p.get("document_url"),
                payload=p.get("payload"),
            ))
        components.append(TemplateComponent(
            type=TemplateComponentType(comp_dict.get("type", "body")),
            sub_type=comp_dict.get("sub_type"),
            index=comp_dict.get("index"),
            parameters=params,
        ))

    template_req = SendTemplateRequest(
        template_name=request.template_name,
        language_code=request.language_code,
        recipient_number=request.recipient_number,
        components=components,
        correlation_id=request.correlation_id,
    )
    return preview_template_payload(template_req)


@router.post("/templates/send")
def send_whatsapp_template(request: SendTemplateAPIRequest):
    """Send a WhatsApp template message through the active provider."""
    components = []
    for comp_dict in request.components:
        params = []
        for p in comp_dict.get("parameters", []):
            params.append(TemplateParameter(
                type=TemplateParameterType(p.get("type", "text")),
                text=p.get("text"),
                image_url=p.get("image_url"),
                video_url=p.get("video_url"),
                document_url=p.get("document_url"),
                payload=p.get("payload"),
            ))
        components.append(TemplateComponent(
            type=TemplateComponentType(comp_dict.get("type", "body")),
            sub_type=comp_dict.get("sub_type"),
            index=comp_dict.get("index"),
            parameters=params,
        ))

    template_req = SendTemplateRequest(
        template_name=request.template_name,
        language_code=request.language_code,
        recipient_number=request.recipient_number,
        components=components,
        correlation_id=request.correlation_id,
    )
    return send_template_message(
        template_req,
        has_approved_context=request.approved,
    )


# ---------------------------------------------------------------------------
# Analytics endpoints
# ---------------------------------------------------------------------------


@router.get("/analytics/summary")
def analytics_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    contact_id: int | None = None,
    provider: str | None = None,
    db: Session = Depends(get_db),
):
    """Get aggregate analytics summary with optional date-range filtering."""
    from datetime import datetime as dt
    start = dt.fromisoformat(start_date) if start_date else None
    end = dt.fromisoformat(end_date) if end_date else None
    return get_analytics_summary(
        db,
        start_date=start,
        end_date=end,
        contact_id=contact_id,
        provider=provider,
    )


@router.get("/analytics/conversations")
def analytics_conversations(
    limit: int = 50,
    contact_id: int | None = None,
    db: Session = Depends(get_db),
):
    """List per-conversation analytics."""
    return {
        "conversations": list_conversation_analytics(db, limit=limit, contact_id=contact_id),
    }


@router.get("/analytics/conversations/{conversation_id}")
def analytics_conversation_detail(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    """Get analytics for a specific conversation."""
    result = get_conversation_analytics(db, conversation_id)
    if result is None:
        return {"error": "Analytics not found for this conversation"}
    return result


# ---------------------------------------------------------------------------
# Handoff endpoints
# ---------------------------------------------------------------------------


class SendTemplateAPIRequest(BaseModel):
    """Request to send a WhatsApp template message."""

    template_name: str = Field(description="Name of the approved Meta template")
    language_code: str = Field(description="Language code (e.g. 'en', 'en_US')")
    recipient_number: str = Field(description="E.164 destination number (+1234567890)")
    components: list[dict] = Field(default_factory=list, description="Template components with parameters")
    correlation_id: str | None = Field(default=None, description="Correlation ID for tracking")
    approved: bool = Field(default=False, description="Pre-approved by operator")


class HandoffRequestAPI(BaseModel):
    """Request human handoff for a conversation."""
    conversation_id: int = Field(description="Conversation to escalate")
    reason: str = Field(default="explicit_user_request", description="Escalation reason")
    detail: str | None = Field(default=None, description="Additional context")


class ActivateHandoffAPI(BaseModel):
    """Activate human handling for a conversation."""
    conversation_id: int = Field(description="Conversation to take over")
    assigned_to: str | None = Field(default=None, description="Human operator name")


class ResolveHandoffAPI(BaseModel):
    """Resolve a handoff."""
    conversation_id: int = Field(description="Conversation to resolve")
    resolution_notes: str | None = Field(default=None, description="Resolution notes")
    return_to_ai: bool = Field(default=True, description="Return conversation to AI after resolution")


@router.get("/handoffs")
def list_handoffs(
    db: Session = Depends(get_db),
):
    """List all pending human handoff requests."""
    handoffs = get_pending_handoffs(db)
    return {
        "handoffs": handoffs,
        "total": len(handoffs),
    }


@router.get("/conversations/{conversation_id}/handoff")
def get_handoff_status(
    conversation_id: int,
    db: Session = Depends(get_db),
):
    """Get the handoff status and context for a conversation."""
    return get_handoff_context(db, conversation_id)


@router.post("/handoff/request")
def request_handoff_endpoint(
    request: HandoffRequestAPI,
    db: Session = Depends(get_db),
):
    """Request human handoff for a conversation."""
    return request_handoff(
        db=db,
        conversation_id=request.conversation_id,
        reason=request.reason,
        detail=request.detail,
    )


@router.post("/handoff/activate")
def activate_handoff_endpoint(
    request: ActivateHandoffAPI,
    db: Session = Depends(get_db),
):
    """Activate human handling for a conversation."""
    return activate_human_handling(
        db=db,
        conversation_id=request.conversation_id,
        assigned_to=request.assigned_to,
    )


@router.post("/handoff/resolve")
def resolve_handoff_endpoint(
    request: ResolveHandoffAPI,
    db: Session = Depends(get_db),
):
    """Resolve a handoff, optionally returning to AI."""
    result = resolve_handoff(
        db=db,
        conversation_id=request.conversation_id,
        resolution_notes=request.resolution_notes,
    )
    if request.return_to_ai and result.get("status") == "resolved":
        ai_result = return_to_ai(db, request.conversation_id)
        result["return_to_ai"] = ai_result
    return result
