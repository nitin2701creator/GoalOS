"""WACRM WhatsApp Business API adapter for GoalOS.

WACRM (https://github.com/ArnasDon/wacrm) is a self-hostable CRM for
WhatsApp using the official Meta WhatsApp Business API. This adapter
communicates with WACRM's public REST API to send messages and parse
webhooks.

WACRM runs as a separate Next.js service. GoalOS communicates with it
via HTTP — never embedding WACRM's runtime directly.

Required environment variables:
    WACRM_API_URL       — Base URL of the WACRM public API (e.g. http://localhost:3000)
    WACRM_API_KEY       — API key for WACRM authentication
    WACRM_WEBHOOK_SECRET — Secret for validating incoming webhooks (optional, for verification)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

from app.integrations.whatsapp.base import BaseWhatsAppAdapter, WhatsAppConfig
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    SendTemplateRequest,
    SendTemplateResponse,
    TemplateStatus,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)

logger = logging.getLogger(__name__)


def wacrm_config_from_env() -> WhatsAppConfig:
    """Build a WACRM config from environment variables."""
    return WhatsAppConfig(
        provider="wacrm",
        api_base_url=os.getenv("WACRM_API_URL", "").strip(),
        auth_token=os.getenv("WACRM_API_KEY", "").strip(),
        webhook_secret=os.getenv("WACRM_WEBHOOK_SECRET", "").strip(),
    )


class WacrmWhatsAppAdapter(BaseWhatsAppAdapter):
    """WACRM REST API adapter for WhatsApp messaging.

    Uses stdlib urllib with Bearer token auth — zero third-party SDK dependencies.

    WACRM is a separate service. This adapter sends HTTP requests to its
    public REST API for sending messages and receiving webhooks.
    """

    name = "wacrm"

    def __init__(self, config: WhatsAppConfig | None = None) -> None:
        super().__init__(config or wacrm_config_from_env())

    def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        """Send an outbound WhatsApp message via WACRM.

        Maps to: POST /api/v1/messages
        """
        if not self.is_configured:
            return SendMessageResponse(
                provider="wacrm",
                status=WhatsAppStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: WACRM API URL not set",
            )

        # Normalize destination number
        from app.integrations.communications.models import normalize_e164

        dest = normalize_e164(request.destination_number)
        if not dest:
            return SendMessageResponse(
                provider="wacrm",
                status=WhatsAppStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )

        try:
            # Build WACRM message payload
            payload: dict[str, Any] = {
                "to": dest,
                "type": request.media_type.value if request.media_url else "text",
            }

            if request.media_url:
                # Media message
                media_type_map = {
                    WhatsAppMediaType.IMAGE: "image",
                    WhatsAppMediaType.VIDEO: "video",
                    WhatsAppMediaType.AUDIO: "audio",
                    WhatsAppMediaType.DOCUMENT: "document",
                }
                wacrm_type = media_type_map.get(request.media_type)
                if wacrm_type:
                    payload["type"] = wacrm_type
                    payload["media_url"] = request.media_url
                    if request.caption:
                        payload["text"] = request.caption
                else:
                    payload["type"] = "text"
                    payload["text"] = request.message or ""
            else:
                # Text message
                payload["text"] = request.message

            body = json.dumps(payload).encode()
            response_data = self._api_call("POST", "/api/v1/messages", body)

            # Handle WACRM error envelope
            if "error" in response_data:
                error_info = response_data["error"]
                error_code = error_info.get("code", "")
                error_msg = error_info.get("message", "Unknown WACRM error")

                return SendMessageResponse(
                    provider="wacrm",
                    status=WhatsAppStatus.FAILED,
                    error=f"PROVIDER_ERROR [{error_code}]: {error_msg}",
                    provider_metadata={"error_code": str(error_code)},
                )

            # Success — WACRM returns data envelope
            data = response_data.get("data", {})
            message_id = data.get("id") or data.get("whatsapp_message_id", "")

            return SendMessageResponse(
                provider="wacrm",
                external_message_id=message_id,
                status=WhatsAppStatus.SENT,
                provider_metadata={
                    "conversation_id": data.get("conversation_id"),
                    "contact_id": data.get("contact_id"),
                    "status": data.get("status"),
                },
            )
        except Exception as exc:
            logger.warning("WACRM send message failed: %s", exc)
            return SendMessageResponse(
                provider="wacrm",
                status=WhatsAppStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def parse_webhook(self, payload: dict[str, Any]) -> WhatsAppWebhookEvent | None:
        """Parse a WACRM webhook payload into a normalized event.

        WACRM webhook format:
        {
          "id": "delivery-uuid",
          "event": "message.received",
          "occurred_at": "2026-07-01T12:00:00.000Z",
          "account_id": "...",
          "data": { ... }
        }
        """
        event_type_str = payload.get("event", "")
        delivery_id = payload.get("id", "")

        if not event_type_str:
            return None

        event_type_map = {
            "message.received": WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            "message.status_updated": None,  # Handled below
            "conversation.created": None,
        }

        # Handle status updates specially
        if event_type_str == "message.status_updated":
            data = payload.get("data", {})
            status_str = data.get("status", "")
            message_id = data.get("whatsapp_message_id", "")
            status_type_map = {
                "sent": WhatsAppWebhookEventType.MESSAGE_SENT,
                "delivered": WhatsAppWebhookEventType.MESSAGE_DELIVERED,
                "read": WhatsAppWebhookEventType.MESSAGE_READ,
                "failed": WhatsAppWebhookEventType.MESSAGE_FAILED,
            }
            event_type = status_type_map.get(status_str)
            if event_type is None or not message_id:
                return None
            return WhatsAppWebhookEvent(
                event_type=event_type,
                provider="wacrm",
                external_message_id=message_id,
                status=status_str,
                metadata={
                    "delivery_id": delivery_id,
                    "occurred_at": payload.get("occurred_at"),
                    "conversation_id": data.get("conversation_id"),
                },
            )

        # Handle incoming messages
        if event_type_str == "message.received":
            data = payload.get("data", {})
            message_id = data.get("whatsapp_message_id", "")
            content_type = data.get("content_type", "text")
            text = data.get("text", "")

            return WhatsAppWebhookEvent(
                event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
                provider="wacrm",
                external_message_id=message_id,
                status="received",
                sender_number=data.get("contact_phone", data.get("from", "")),
                metadata={
                    "delivery_id": delivery_id,
                    "occurred_at": payload.get("occurred_at"),
                    "conversation_id": data.get("conversation_id"),
                    "contact_id": data.get("contact_id"),
                    "content_type": content_type,
                    "body": text[:500] if text else None,
                    "media_url": data.get("media_url"),
                },
            )

        return None

    def verify_webhook(self, payload: bytes, signature: str | None) -> bool:
        """Verify WACRM webhook signature using HMAC-SHA256.

        WACRM sends X-Wacrm-Signature header.
        """
        if not self.config.webhook_secret:
            # No secret configured — accept all (dev mode)
            return True
        if not signature:
            return False
        expected = hmac.new(
            self.config.webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def send_template(self, request: SendTemplateRequest) -> SendTemplateResponse:
        """Send an approved template message via WACRM.

        Maps to: POST /api/v1/messages with type=template
        """
        if not self.is_configured:
            return SendTemplateResponse(
                provider="wacrm",
                status=TemplateStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: WACRM API URL not set",
                correlation_id=request.correlation_id,
            )

        from app.integrations.communications.models import normalize_e164

        dest = normalize_e164(request.recipient_number)
        if not dest:
            return SendTemplateResponse(
                provider="wacrm",
                status=TemplateStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.recipient_number}' to E.164",
                correlation_id=request.correlation_id,
            )

        try:
            # Build WACRM template payload
            params = []
            for comp in request.components:
                for param in comp.parameters:
                    if param.text:
                        params.append(param.text)

            payload: dict[str, Any] = {
                "to": dest,
                "type": "template",
                "template": {
                    "name": request.template_name.strip(),
                    "language": request.language_code.strip(),
                    "params": params,
                },
            }

            body = json.dumps(payload).encode()
            response_data = self._api_call("POST", "/api/v1/messages", body)

            if "error" in response_data:
                error_info = response_data["error"]
                error_code = error_info.get("code", "")
                error_msg = error_info.get("message", "Unknown error")
                status = TemplateStatus.REJECTED if "template" in error_msg.lower() else TemplateStatus.FAILED
                return SendTemplateResponse(
                    provider="wacrm",
                    status=status,
                    error=f"PROVIDER_ERROR [{error_code}]: {error_msg}",
                    correlation_id=request.correlation_id,
                )

            data = response_data.get("data", {})
            message_id = data.get("id") or data.get("whatsapp_message_id", "")

            return SendTemplateResponse(
                provider="wacrm",
                external_message_id=message_id,
                status=TemplateStatus.SENT,
                correlation_id=request.correlation_id,
                provider_metadata={
                    "conversation_id": data.get("conversation_id"),
                    "contact_id": data.get("contact_id"),
                },
            )
        except Exception as exc:
            logger.warning("WACRM template send failed: %s", exc)
            return SendTemplateResponse(
                provider="wacrm",
                status=TemplateStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
                correlation_id=request.correlation_id,
            )

    def get_status(self) -> dict[str, Any]:
        """Check WACRM API health via GET /api/v1/me."""
        base = super().get_status()
        if not self.is_configured:
            return base
        try:
            response = self._api_call("GET", "/api/v1/me")
            if "data" in response:
                base["api_reachable"] = True
                base["account_name"] = response["data"].get("account", {}).get("name", "")
                base["scopes"] = response["data"].get("key", {}).get("scopes", [])
            elif "error" in response:
                base["api_reachable"] = True
                base["auth_error"] = response["error"].get("code")
            else:
                base["api_reachable"] = False
        except Exception:
            base["api_reachable"] = False
        return base

    def _api_call(
        self, method: str, path: str, body: bytes | None = None
    ) -> dict:
        """Make an authenticated WACRM API call using stdlib."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        url = f"{self.config.api_base_url.rstrip('/')}{path}"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.config.auth_token:
            headers["Authorization"] = f"Bearer {self.config.auth_token}"

        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                data = response.read()
                return json.loads(data.decode())
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            logger.error(
                "WACRM API %s %s returned %s: %s",
                method, path, exc.code, error_body[:200],
            )
            try:
                return json.loads(error_body)
            except (json.JSONDecodeError, ValueError):
                raise ConnectionError(
                    f"WACRM API error {exc.code}: {error_body[:200]}"
                ) from exc
