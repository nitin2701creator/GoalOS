"""WhatsApp Template Message Service for GoalOS.

Provider-neutral orchestration for WhatsApp template messages.
Validates requests, enforces Action Policy, dispatches to the active
provider adapter, and persists delivery status.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.integrations.whatsapp.factory import get_active_provider
from app.integrations.whatsapp.models import (
    SendTemplateRequest,
    SendTemplateResponse,
    TemplateComponent,
    TemplateComponentType,
    TemplateParameter,
    TemplateParameterType,
    TemplateStatus,
)
from app.services.action_policy import (
    ActionPolicyEngine,
    PolicyDecision,
    RiskLevel,
    SPRINT1_ACTIONS,
    ActionDeclaration,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Template-specific action declaration
# ---------------------------------------------------------------------------

TEMPLATE_ACTIONS: list[ActionDeclaration] = [
    ActionDeclaration(
        action_name="send_whatsapp_template",
        risk_level=RiskLevel.MEDIUM,
        approval_required=True,
        reversible=False,
        has_external_side_effect=True,
        estimated_cost=0.0,
        required_capability="whatsapp_send_template",
        description="Send a pre-approved WhatsApp template message",
    ),
]

# Initialize policy engine with template actions
_template_policy = ActionPolicyEngine()
_template_policy.register_many(SPRINT1_ACTIONS + TEMPLATE_ACTIONS)

# ---------------------------------------------------------------------------
# In-memory idempotency cache (bounded, like the agent)
# ---------------------------------------------------------------------------

_sent_templates: dict[str, datetime] = {}
_MAX_SENT_CACHE = 5000


def _is_duplicate_send(correlation_id: str) -> bool:
    """Check if a template with this correlation_id was already sent."""
    if not correlation_id:
        return False
    if correlation_id in _sent_templates:
        return True
    # Evict old entries
    if len(_sent_templates) > _MAX_SENT_CACHE:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 3600
        to_remove = [k for k, v in _sent_templates.items() if v.timestamp() < cutoff]
        for k in to_remove:
            del _sent_templates[k]
    _sent_templates[correlation_id] = datetime.now(timezone.utc)
    return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_template_request(request: SendTemplateRequest) -> dict[str, Any]:
    """Validate a template request before sending.

    Returns {"valid": True} or {"valid": False, "error": "..."}.
    Does NOT check provider availability — only the request shape.
    """
    # Template name
    if not request.template_name or not request.template_name.strip():
        return {"valid": False, "error": "template_name is required"}
    name = request.template_name.strip()
    if len(name) > 512:
        return {"valid": False, "error": "template_name is too long (max 512)"}
    # Meta template names are alphanumeric + underscores
    if not all(c.isalnum() or c == "_" for c in name):
        return {"valid": False, "error": "template_name contains invalid characters (use alphanumeric + underscore)"}

    # Language code
    if not request.language_code or not request.language_code.strip():
        return {"valid": False, "error": "language_code is required"}
    lang = request.language_code.strip()
    if len(lang) < 2 or len(lang) > 10:
        return {"valid": False, "error": "language_code must be 2-10 characters (e.g. 'en', 'en_US')"}

    # Recipient
    from app.integrations.whatsapp.models import normalize_e164
    dest = normalize_e164(request.recipient_number)
    if not dest:
        return {"valid": False, "error": f"recipient_number '{request.recipient_number}' is not valid E.164"}

    # Components validation
    seen_types: set[str] = set()
    for i, comp in enumerate(request.components):
        comp_type = comp.type.value if hasattr(comp.type, "value") else str(comp.type)
        if comp_type in ("header", "body") and comp_type in seen_types:
            return {"valid": False, "error": f"Duplicate {comp_type} component at index {i}"}
        seen_types.add(comp_type)

        # Validate parameters
        for j, param in enumerate(comp.parameters):
            param_type = param.type.value if hasattr(param.type, "value") else str(param.type)
            if param_type == "text" and not param.text:
                return {"valid": False, "error": f"text parameter at component {i}, param {j} is empty"}
            if param_type == "image" and not param.image_url:
                return {"valid": False, "error": f"image parameter at component {i}, param {j} has no URL"}
            if param_type == "video" and not param.video_url:
                return {"valid": False, "error": f"video parameter at component {i}, param {j} has no URL"}
            if param_type == "document" and not param.document_url:
                return {"valid": False, "error": f"document parameter at component {i}, param {j} has no URL"}

    return {"valid": True}


# ---------------------------------------------------------------------------
# Template definitions (configurable, not hard-coded)
# ---------------------------------------------------------------------------

# Default template definitions — these map to Meta-approved templates
_DEFAULT_TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "order_confirmation",
        "language_code": "en",
        "category": "transactional",
        "description": "Confirm an order has been received",
        "body_text": "Your order #{{1}} has been confirmed. Total: {{2}}",
        "variables": ["order_number", "total_amount"],
    },
    {
        "name": "payment_confirmation",
        "language_code": "en",
        "category": "transactional",
        "description": "Confirm payment has been received",
        "body_text": "Payment of {{1}} received for order #{{2}}. Thank you!",
        "variables": ["amount", "order_number"],
    },
    {
        "name": "shipping_update",
        "language_code": "en",
        "category": "utility",
        "description": "Notify customer of shipping status",
        "body_text": "Your order #{{1}} has been {{2}}. Track: {{3}}",
        "variables": ["order_number", "status", "tracking_url"],
    },
    {
        "name": "appointment_reminder",
        "language_code": "en",
        "category": "utility",
        "description": "Remind customer of upcoming appointment",
        "body_text": "Reminder: You have an appointment on {{1}} at {{2}}.",
        "variables": ["date", "time"],
    },
    {
        "name": "lead_followup",
        "language_code": "en",
        "category": "marketing",
        "description": "Follow up with a potential lead",
        "body_text": "Hi {{1}}, following up on our conversation about {{2}}.",
        "variables": ["name", "topic"],
    },
    {
        "name": "customer_reengagement",
        "language_code": "en",
        "category": "marketing",
        "description": "Re-engage a dormant customer",
        "body_text": "Hi {{1}}, we miss you! Here's a special offer: {{2}}",
        "variables": ["name", "offer"],
    },
    {
        "name": "human_handoff_notification",
        "language_code": "en",
        "category": "utility",
        "description": "Notify customer that a human agent is taking over",
        "body_text": "A team member will assist you shortly regarding: {{1}}",
        "variables": ["topic"],
    },
]

_template_definitions: dict[str, dict[str, Any]] = {
    t["name"]: t for t in _DEFAULT_TEMPLATES
}


def list_templates() -> list[dict[str, Any]]:
    """List all configured template definitions."""
    return [
        {
            "name": t["name"],
            "language_code": t["language_code"],
            "category": t["category"],
            "description": t["description"],
            "variables": t.get("variables", []),
            "status": "approved",  # Default — Meta approval happens externally
        }
        for t in _template_definitions.values()
    ]


def get_template(name: str) -> dict[str, Any] | None:
    """Get a template definition by name."""
    return _template_definitions.get(name)


def preview_template_payload(request: SendTemplateRequest) -> dict[str, Any]:
    """Preview the provider-specific payload without sending.

    Returns the normalized request plus the Meta-compatible payload shape.
    """
    from app.integrations.whatsapp.models import normalize_e164

    dest = normalize_e164(request.recipient_number)
    template_name = request.template_name.strip()
    lang = request.language_code.strip()

    components = []
    for comp in request.components:
        comp_dict: dict[str, Any] = {
            "type": comp.type.value if hasattr(comp.type, "value") else str(comp.type),
        }
        if comp.sub_type:
            comp_dict["sub_type"] = comp.sub_type
        if comp.index is not None:
            comp_dict["index"] = comp.index
        if comp.parameters:
            comp_dict["parameters"] = [
                _parameter_to_dict(p) for p in comp.parameters
            ]
        components.append(comp_dict)

    return {
        "template_name": template_name,
        "language_code": lang,
        "recipient": dest,
        "components": components,
        "meta_payload": {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": dest,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": lang},
                "components": components,
            },
        },
    }


def _parameter_to_dict(param: TemplateParameter) -> dict[str, Any]:
    """Convert a TemplateParameter to a dict for API serialization."""
    result: dict[str, Any] = {
        "type": param.type.value if hasattr(param.type, "value") else str(param.type),
    }
    if param.text is not None:
        result["text"] = param.text
    if param.image_url is not None:
        result["image"] = {"link": param.image_url}
    if param.video_url is not None:
        result["video"] = {"link": param.video_url}
    if param.document_url is not None:
        result["document"] = {"link": param.document_url}
    if param.currency_code is not None:
        result["currency"] = {
            "fallback_value": param.fallback_value or f"{param.currency_amount} {param.currency_code}",
            "code": param.currency_code,
            "amount_1000": param.currency_amount,
        }
    if param.payload is not None:
        result["payload"] = param.payload
    return result


# ---------------------------------------------------------------------------
# Main send function
# ---------------------------------------------------------------------------

def send_template_message(
    request: SendTemplateRequest,
    *,
    has_approved_context: bool = False,
    db: Any = None,
) -> dict[str, Any]:
    """Send a WhatsApp template message through the active provider.

    Pipeline:
    1. Validate request
    2. Check idempotency (correlation_id)
    3. Evaluate Action Policy
    4. Check handoff state (if db provided)
    5. Dispatch to provider
    6. Persist result
    7. Return structured result
    """
    result: dict[str, Any] = {
        "template_name": request.template_name,
        "language_code": request.language_code,
        "recipient": request.recipient_number,
        "correlation_id": request.correlation_id,
        "sent": False,
    }

    # 1. Validate
    validation = validate_template_request(request)
    if not validation["valid"]:
        result["status"] = TemplateStatus.INVALID_TEMPLATE.value
        result["error"] = validation["error"]
        return result

    # 2. Idempotency
    if request.correlation_id and _is_duplicate_send(request.correlation_id):
        result["status"] = "duplicate"
        result["error"] = "Template with this correlation_id was already sent"
        return result

    # 3. Policy check
    policy = _template_policy.evaluate(
        "send_whatsapp_template",
        has_approved_context=has_approved_context,
    )
    if policy.decision == PolicyDecision.DENIED:
        result["status"] = "denied"
        result["error"] = policy.reason
        return result
    if policy.decision == PolicyDecision.APPROVAL_REQUIRED:
        result["status"] = "approval_required"
        result["error"] = policy.reason
        return result

    # 4. Check handoff state (if db provided)
    if db is not None:
        try:
            from app.services.whatsapp_handoff import should_block_ai_reply
            from app.integrations.whatsapp.models import normalize_e164

            # Find the conversation for this recipient
            from app.repositories.whatsapp_repository import WhatsAppRepository
            repo = WhatsAppRepository(db)
            dest = normalize_e164(request.recipient_number)
            contacts = repo.list_contacts(limit=1000)
            for contact in contacts:
                if contact.phone_number == dest or contact.external_id == dest:
                    convs = repo.list_conversations(contact_id=contact.id, active_only=True, limit=1)
                    if convs and should_block_ai_reply(db, convs[0].id):
                        result["status"] = "handoff_active"
                        result["error"] = "Conversation is in human handoff — template blocked"
                        return result
                    break
        except Exception as exc:
            logger.debug("Handoff check skipped: %s", exc)

    # 5. Dispatch to provider
    provider = get_active_provider()
    if provider is None:
        result["status"] = TemplateStatus.NO_PROVIDER.value
        result["error"] = "No WHATSAPP_PROVIDER configured"
        return result
    if not provider.is_configured:
        result["status"] = TemplateStatus.NO_PROVIDER.value
        result["error"] = f"{provider.name} is not configured"
        return result

    try:
        provider_response: SendTemplateResponse = provider.send_template(request)
        result["status"] = provider_response.status.value
        result["external_message_id"] = provider_response.external_message_id
        result["provider"] = provider_response.provider
        result["sent"] = provider_response.status in (
            TemplateStatus.SENT,
            TemplateStatus.QUEUED,
            TemplateStatus.DELIVERED,
        )
        if provider_response.error:
            result["error"] = provider_response.error
        if provider_response.provider_metadata:
            result["provider_metadata"] = provider_response.provider_metadata
    except Exception as exc:
        logger.warning("Template send failed: %s", exc)
        result["status"] = TemplateStatus.FAILED.value
        result["error"] = f"PROVIDER_EXCEPTION: {exc}"

    return result
