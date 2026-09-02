"""Meta WhatsApp Cloud API adapter for GoalOS.

Implements the BaseWhatsAppAdapter interface for the Meta WhatsApp
Business Platform Cloud API (https://developers.facebook.com/docs/whatsapp/cloud-api).

This adapter communicates with Meta's Graph API directly using stdlib HTTP —
zero third-party SDK dependencies required.

Meta Cloud API is a cloud-hosted service, so no additional runtime process
is needed on the KVM. GoalOS just needs valid credentials and a webhook URL.

Required environment variables for outbound messaging:
    META_WHATSAPP_ACCESS_TOKEN   — Meta Business API access token
    META_WHATSAPP_PHONE_NUMBER_ID — Phone number ID from Meta dashboard

Required environment variables for webhook verification:
    META_WHATSAPP_VERIFY_TOKEN   — Custom verification token set in Meta dashboard

Required environment variables for webhook signature validation:
    META_WHATSAPP_APP_SECRET     — App secret from Meta dashboard

Optional:
    META_WHATSAPP_BUSINESS_ACCOUNT_ID — Business account ID (for status/health checks)
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

_META_GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


def meta_config_from_env() -> WhatsAppConfig:
    """Build a Meta WhatsApp config from environment variables."""
    phone_number_id = os.getenv("META_WHATSAPP_PHONE_NUMBER_ID", "").strip()
    access_token = os.getenv("META_WHATSAPP_ACCESS_TOKEN", "").strip()
    # For Meta, the api_base_url is constructed from the phone_number_id
    api_base = f"{_META_GRAPH_API_BASE}/{phone_number_id}" if phone_number_id else ""
    return WhatsAppConfig(
        provider="meta",
        api_base_url=api_base,
        auth_token=access_token,
        webhook_secret=os.getenv("META_WHATSAPP_APP_SECRET", "").strip(),
        extra={
            "phone_number_id": phone_number_id,
            "business_account_id": os.getenv("META_WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip(),
            "verify_token": os.getenv("META_WHATSAPP_VERIFY_TOKEN", "").strip(),
        },
    )


class MetaWhatsAppAdapter(BaseWhatsAppAdapter):
    """Meta WhatsApp Cloud API adapter.

    Uses stdlib urllib with Bearer token auth — zero third-party SDK dependencies.

    Meta Cloud API is cloud-hosted, so no separate runtime process is needed.
    GoalOS communicates directly with Meta's Graph API.
    """

    name = "meta"

    def __init__(self, config: WhatsAppConfig | None = None) -> None:
        super().__init__(config or meta_config_from_env())

    def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        if not self.is_configured:
            return SendMessageResponse(
                provider="meta",
                status=WhatsAppStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: Meta WhatsApp credentials not set",
            )

        # Normalize destination number
        from app.integrations.communications.models import normalize_e164

        dest = normalize_e164(request.destination_number)
        if not dest:
            return SendMessageResponse(
                provider="meta",
                status=WhatsAppStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )

        try:
            # Build Meta-compatible messaging payload
            messaging_product = "whatsapp"
            recipient_type = "individual"

            if request.media_url and request.media_type != WhatsAppMediaType.TEXT:
                # Media message
                media_type_map = {
                    WhatsAppMediaType.IMAGE: "image",
                    WhatsAppMediaType.VIDEO: "video",
                    WhatsAppMediaType.AUDIO: "audio",
                    WhatsAppMediaType.DOCUMENT: "document",
                }
                meta_type = media_type_map.get(request.media_type)
                if meta_type is None:
                    return SendMessageResponse(
                        provider="meta",
                        status=WhatsAppStatus.FAILED,
                        error=f"UNSUPPORTED_MEDIA_TYPE: Meta does not support '{request.media_type.value}'",
                    )

                media_payload: dict[str, Any] = {"link": request.media_url}
                if request.caption and meta_type in ("image", "video", "document"):
                    media_payload["caption"] = request.caption

                payload: dict[str, Any] = {
                    "messaging_product": messaging_product,
                    "recipient_type": recipient_type,
                    "to": dest,
                    "type": meta_type,
                    meta_type: media_payload,
                }
            else:
                # Text message
                payload = {
                    "messaging_product": messaging_product,
                    "recipient_type": recipient_type,
                    "to": dest,
                    "type": "text",
                    "text": {"body": request.message},
                }

            body = json.dumps(payload).encode()
            response_data = self._api_call("POST", "/messages", body)

            # Meta returns errors in the top-level error field
            if "error" in response_data:
                error_info = response_data["error"]
                error_code = error_info.get("code", "")
                error_msg = error_info.get("message", "Unknown Meta error")
                error_subcode = error_info.get("error_subcode", "")

                # Map common Meta error codes
                status = self._map_error_status(error_code)
                error_detail = f"PROVIDER_ERROR [{error_code}"
                if error_subcode:
                    error_detail += f"/{error_subcode}"
                error_detail += f"]: {error_msg}"

                return SendMessageResponse(
                    provider="meta",
                    status=status,
                    error=error_detail,
                    provider_metadata={
                        "error_code": str(error_code),
                        "error_subcode": str(error_subcode),
                        "fbtrace_id": error_info.get("fbtrace_id", ""),
                    },
                )

            # Success — Meta returns contacts and messages arrays
            contacts = response_data.get("contacts", [])
            messages = response_data.get("messages", [])

            message_id = messages[0]["id"] if messages else None
            contact_wa_id = contacts[0].get("wa_id") if contacts else dest

            return SendMessageResponse(
                provider="meta",
                external_message_id=message_id,
                status=WhatsAppStatus.SENT,
                provider_metadata={
                    "wa_id": contact_wa_id,
                    "message_id": message_id,
                },
            )
        except Exception as exc:
            logger.warning("Meta WhatsApp send message failed: %s", exc)
            return SendMessageResponse(
                provider="meta",
                status=WhatsAppStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def parse_webhook(self, payload: dict[str, Any]) -> WhatsAppWebhookEvent | None:
        """Parse a Meta WhatsApp webhook payload into a normalized event.

        Meta webhook format (Cloud API):
        {
          "object": "whatsapp_business_account",
          "entry": [{
            "id": "WABA_ID",
            "changes": [{
              "value": {
                "messaging_product": "whatsapp",
                "metadata": {...},
                "statuses": [{
                  "id": "MESSAGE_ID",
                  "status": "delivered",
                  "timestamp": "...",
                  "recipient_id": "PHONE",
                  "errors": [...]
                }],
                "messages": [{
                  "from": "PHONE",
                  "id": "MESSAGE_ID",
                  "timestamp": "...",
                  "type": "text",
                  "text": {"body": "..."}
                }]
              },
              "field": "messages"
            }]
          }]
        }
        """
        if payload.get("object") != "whatsapp_business_account":
            return None

        entries = payload.get("entry", [])
        if not entries:
            return None

        # Process first entry's first change
        changes = entries[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})

        # Check for status updates
        statuses = value.get("statuses", [])
        if statuses:
            return self._parse_status(statuses[0])

        # Check for incoming messages
        messages = value.get("messages", [])
        if messages:
            return self._parse_incoming(messages[0], value.get("metadata", {}))

        return None

    def _parse_status(self, status: dict[str, Any]) -> WhatsAppWebhookEvent | None:
        """Parse a Meta status update."""
        meta_status = status.get("status", "")
        message_id = status.get("id", "")

        if not message_id:
            return None

        status_map = {
            "sent": WhatsAppWebhookEventType.MESSAGE_SENT,
            "delivered": WhatsAppWebhookEventType.MESSAGE_DELIVERED,
            "read": WhatsAppWebhookEventType.MESSAGE_READ,
            "failed": WhatsAppWebhookEventType.MESSAGE_FAILED,
            "pending": WhatsAppWebhookEventType.MESSAGE_SENT,
            "accepted": WhatsAppWebhookEventType.MESSAGE_SENT,
            "planned": WhatsAppWebhookEventType.MESSAGE_SENT,
        }

        event_type = status_map.get(meta_status)
        if event_type is None:
            return None

        # Extract error information
        errors = status.get("errors", [])
        error_code = None
        error_message = None
        if errors:
            error_code = str(errors[0].get("code", ""))
            error_message = errors[0].get("message", "")

        return WhatsAppWebhookEvent(
            event_type=event_type,
            provider="meta",
            external_message_id=message_id,
            status=meta_status,
            destination_number=status.get("recipient_id", ""),
            error_code=error_code,
            error_message=error_message,
            metadata={
                "timestamp": status.get("timestamp"),
                "conversation": status.get("conversation"),
                "pricing": status.get("pricing"),
            },
        )

    def _parse_incoming(
        self, message: dict[str, Any], metadata: dict[str, Any]
    ) -> WhatsAppWebhookEvent | None:
        """Parse a Meta incoming message."""
        message_id = message.get("id", "")
        sender = message.get("from", "")

        if not message_id:
            return None

        # Determine content from message type
        msg_type = message.get("type", "text")
        content = ""
        media_url = None

        if msg_type == "text":
            content = message.get("text", {}).get("body", "")
        elif msg_type in ("image", "video", "audio", "document"):
            media_data = message.get(msg_type, {})
            media_url = media_data.get("link")
            content = media_data.get("caption", "")
        elif msg_type == "location":
            lat = message.get("location", {}).get("latitude")
            lng = message.get("location", {}).get("longitude")
            content = f"Location: {lat},{lng}" if lat and lng else "Location shared"
        elif msg_type == "contacts":
            contacts = message.get("contacts", [])
            names = [c.get("name", {}).get("formatted_name", "") for c in contacts]
            content = f"Contact: {', '.join(names)}" if names else "Contact shared"
        else:
            content = f"[{msg_type}]"

        return WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="meta",
            external_message_id=message_id,
            status="received",
            sender_number=sender,
            metadata={
                "type": msg_type,
                "body": content[:500] if content else None,
                "media_url": media_url,
                "timestamp": message.get("timestamp"),
                "context": message.get("context"),
                "phone_number_id": metadata.get("phone_number_id"),
                "display_phone_number": metadata.get("display_phone_number"),
            },
        )

    def send_template(self, request: SendTemplateRequest) -> SendTemplateResponse:
        """Send an approved template message via Meta Cloud API.

        Meta template endpoint:
        POST /v21.0/{phone_number_id}/messages
        {
          "messaging_product": "whatsapp",
          "recipient_type": "individual",
          "to": "<E.164>",
          "type": "template",
          "template": {
            "name": "<template-name>",
            "language": {"code": "en"},
            "components": [...]
          }
        }
        """
        if not self.is_configured:
            return SendTemplateResponse(
                provider="meta",
                status=TemplateStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: Meta WhatsApp credentials not set",
                correlation_id=request.correlation_id,
            )

        # Normalize destination
        from app.integrations.communications.models import normalize_e164

        dest = normalize_e164(request.recipient_number)
        if not dest:
            return SendTemplateResponse(
                provider="meta",
                status=TemplateStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.recipient_number}' to E.164",
                correlation_id=request.correlation_id,
            )

        try:
            # Build Meta template payload
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
                    params = []
                    for p in comp.parameters:
                        p_dict: dict[str, Any] = {
                            "type": p.type.value if hasattr(p.type, "value") else str(p.type),
                        }
                        if p.text is not None:
                            p_dict["text"] = p.text
                        if p.image_url is not None:
                            p_dict["image"] = {"link": p.image_url}
                        if p.video_url is not None:
                            p_dict["video"] = {"link": p.video_url}
                        if p.document_url is not None:
                            p_dict["document"] = {"link": p.document_url}
                        if p.payload is not None:
                            p_dict["payload"] = p.payload
                        params.append(p_dict)
                    comp_dict["parameters"] = params
                components.append(comp_dict)

            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": dest,
                "type": "template",
                "template": {
                    "name": request.template_name.strip(),
                    "language": {"code": request.language_code.strip()},
                },
            }
            if components:
                payload["template"]["components"] = components

            body = json.dumps(payload).encode()
            response_data = self._api_call("POST", "/messages", body)

            # Handle errors
            if "error" in response_data:
                error_info = response_data["error"]
                error_code = error_info.get("code", "")
                error_msg = error_info.get("message", "Unknown Meta error")
                error_subcode = error_info.get("error_subcode", "")

                # Determine if this is a template rejection
                status = TemplateStatus.REJECTED if error_code in (131047, 131046) else TemplateStatus.FAILED
                error_detail = f"PROVIDER_ERROR [{error_code}"
                if error_subcode:
                    error_detail += f"/{error_subcode}"
                error_detail += f"]: {error_msg}"

                return SendTemplateResponse(
                    provider="meta",
                    status=status,
                    error=error_detail,
                    correlation_id=request.correlation_id,
                    provider_metadata={
                        "error_code": str(error_code),
                        "error_subcode": str(error_subcode),
                        "fbtrace_id": error_info.get("fbtrace_id", ""),
                    },
                )

            # Success
            messages = response_data.get("messages", [])
            message_id = messages[0]["id"] if messages else None
            contacts = response_data.get("contacts", [])
            contact_wa_id = contacts[0].get("wa_id") if contacts else dest

            return SendTemplateResponse(
                provider="meta",
                external_message_id=message_id,
                status=TemplateStatus.SENT,
                correlation_id=request.correlation_id,
                provider_metadata={
                    "wa_id": contact_wa_id,
                    "message_id": message_id,
                    "template_name": request.template_name,
                },
            )
        except Exception as exc:
            logger.warning("Meta WhatsApp template send failed: %s", exc)
            return SendTemplateResponse(
                provider="meta",
                status=TemplateStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
                correlation_id=request.correlation_id,
            )

    def verify_webhook(self, payload: bytes, signature: str | None) -> bool:
        """Verify Meta webhook signature using HMAC-SHA256.

        Meta sends X-Hub-Signature-256 header with:
        sha256=<hex-digest>
        """
        app_secret = self.config.webhook_secret
        if not app_secret:
            # No secret configured — accept all (dev mode)
            return True
        if not signature:
            return False

        # Meta format: "sha256=<hex>"
        if signature.startswith("sha256="):
            expected_hex = signature[7:]
        else:
            expected_hex = signature

        computed = hmac.new(
            app_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(computed, expected_hex)

    def verify_webhook_challenge(
        self, mode: str, token: str, challenge: str
    ) -> str | None:
        """Handle Meta's webhook verification challenge.

        When Meta sets up a webhook, it sends a GET request with:
        - hub.mode=subscribe
        - hub.verify_token=<your-token>
        - hub.challenge=<random-string>

        If verify_token matches, return the challenge string.
        Otherwise return None (reject).
        """
        if mode != "subscribe":
            return None
        expected_token = self.config.extra.get("verify_token", "")
        if not expected_token or token != expected_token:
            return None
        return challenge

    def get_status(self) -> dict[str, Any]:
        """Check Meta WhatsApp API health."""
        base = super().get_status()
        if not self.is_configured:
            return base

        phone_id = self.config.extra.get("phone_number_id", "")
        biz_id = self.config.extra.get("business_account_id", "")

        base["phone_number_id"] = phone_id
        base["business_account_id"] = biz_id

        # Verify token validity by fetching phone number info
        if phone_id:
            try:
                response = self._api_call("GET", f"/{phone_id}")
                base["api_reachable"] = True
                base["verified_name"] = response.get("verified_name", "")
                base["quality_rating"] = response.get("quality_rating", "")
            except Exception:
                base["api_reachable"] = False

        return base

    def _map_error_status(self, error_code: int | str) -> WhatsAppStatus:
        """Map Meta error codes to WhatsAppStatus."""
        try:
            code = int(error_code)
        except (ValueError, TypeError):
            return WhatsAppStatus.FAILED

        # Common Meta error codes
        if code == 190:
            # Expired/invalid access token
            return WhatsAppStatus.FAILED
        if code in (368, 131047, 131046):
            # Rate limiting / blocked
            return WhatsAppStatus.FAILED
        if code == 100:
            # Invalid parameter
            return WhatsAppStatus.FAILED
        if code == 131026:
            # Message undeliverable
            return WhatsAppStatus.FAILED
        return WhatsAppStatus.FAILED

    def _api_call(
        self, method: str, path: str, body: bytes | None = None
    ) -> dict:
        """Make an authenticated Meta Graph API call using stdlib."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        # Construct URL
        if path.startswith("/"):
            url = f"{_META_GRAPH_API_BASE}{path}"
        else:
            url = f"{self.config.api_base_url}/{path}"

        headers: dict[str, str] = {
            "Content-Type": "application/json",
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
                "Meta WhatsApp API %s %s returned %s: %s",
                method, path, exc.code, error_body[:200],
            )
            try:
                return json.loads(error_body)
            except (json.JSONDecodeError, ValueError):
                raise ConnectionError(
                    f"Meta WhatsApp API error {exc.code}: {error_body[:200]}"
                ) from exc
