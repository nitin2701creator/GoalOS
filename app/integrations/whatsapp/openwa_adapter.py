"""OpenWA WhatsApp adapter for GoalOS.

OpenWA (https://github.com/rmyndharis/OpenWA) is a self-hosted
WhatsApp Web automation library. This adapter communicates with
an OpenWA REST API instance (separate process) using stdlib HTTP.

OpenWA must be deployed as a separate service/container. GoalOS
communicates with it via its REST API — never embedding the
OpenWA runtime directly.

Required environment variables:
    OPENWA_API_URL      — Base URL of the OpenWA REST API (e.g. http://localhost:5800)
    OPENWA_AUTH_TOKEN   — Authentication token for OpenWA API
    OPENWA_WEBHOOK_SECRET — Secret for validating incoming webhooks
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import base64
from typing import Any

from app.integrations.whatsapp.base import BaseWhatsAppAdapter, WhatsAppConfig
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)

logger = logging.getLogger(__name__)


def openwa_config_from_env() -> WhatsAppConfig:
    """Build an OpenWA config from environment variables."""
    return WhatsAppConfig(
        provider="openwa",
        api_base_url=os.getenv("OPENWA_API_URL", "").strip(),
        auth_token=os.getenv("OPENWA_AUTH_TOKEN", "").strip(),
        webhook_secret=os.getenv("OPENWA_WEBHOOK_SECRET", "").strip(),
    )


class OpenWAAdapter(BaseWhatsAppAdapter):
    """OpenWA REST API adapter for WhatsApp messaging.

    Uses stdlib urllib with token auth — zero third-party SDK dependencies.

    OpenWA runs as a separate service. This adapter sends HTTP requests
    to its REST API for sending messages and receiving webhooks.
    """

    name = "openwa"

    def __init__(self, config: WhatsAppConfig | None = None) -> None:
        super().__init__(config or openwa_config_from_env())

    def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        if not self.is_configured:
            return SendMessageResponse(
                provider="openwa",
                status=WhatsAppStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: OpenWA API URL not set",
            )

        # Normalize destination number
        from app.integrations.communications.models import normalize_e164

        dest = normalize_e164(request.destination_number)
        if not dest:
            return SendMessageResponse(
                provider="openwa",
                status=WhatsAppStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )

        try:
            payload: dict[str, Any] = {
                "to": dest,
                "text": request.message,
            }
            if request.media_url:
                payload["media"] = {
                    "url": request.media_url,
                    "type": request.media_type.value,
                }
                if request.caption:
                    payload["media"]["caption"] = request.caption

            body = json.dumps(payload).encode()
            response_data = self._api_call("POST", "/api/send", body)

            if "error" in response_data:
                return SendMessageResponse(
                    provider="openwa",
                    status=WhatsAppStatus.FAILED,
                    error=f"PROVIDER_ERROR: {response_data['error']}",
                    provider_metadata=response_data,
                )

            return SendMessageResponse(
                provider="openwa",
                external_message_id=response_data.get("messageId"),
                status=WhatsAppStatus.SENT,
                provider_metadata={
                    "to": dest,
                    "chatId": response_data.get("chatId"),
                    "timestamp": response_data.get("timestamp"),
                },
            )
        except Exception as exc:
            logger.warning("OpenWA send message failed: %s", exc)
            return SendMessageResponse(
                provider="openwa",
                status=WhatsAppStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def parse_webhook(self, payload: dict[str, Any]) -> WhatsAppWebhookEvent | None:
        """Parse an OpenWA webhook payload into a normalized event."""
        event_type_str = payload.get("event", "")
        message_id = payload.get("messageId", payload.get("id", ""))

        if not message_id and not event_type_str:
            return None

        event_type_map = {
            "message": WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            "message.sent": WhatsAppWebhookEventType.MESSAGE_SENT,
            "message.delivered": WhatsAppWebhookEventType.MESSAGE_DELIVERED,
            "message.read": WhatsAppWebhookEventType.MESSAGE_READ,
            "message.error": WhatsAppWebhookEventType.MESSAGE_FAILED,
            "contact.update": WhatsAppWebhookEventType.CONTACT_UPDATE,
            "presence.update": WhatsAppWebhookEventType.PRESENCE_UPDATE,
        }

        event_type = event_type_map.get(event_type_str)
        if event_type is None:
            return None

        return WhatsAppWebhookEvent(
            event_type=event_type,
            provider="openwa",
            external_message_id=message_id,
            status=payload.get("status", event_type_str),
            sender_number=payload.get("from", payload.get("author", "")),
            destination_number=payload.get("to", ""),
            error_code=payload.get("errorCode"),
            error_message=payload.get("errorMessage"),
            metadata={
                "chatId": payload.get("chatId"),
                "timestamp": payload.get("timestamp"),
                "body": payload.get("body", "")[:200] if payload.get("body") else None,
            },
        )

    def verify_webhook(self, payload: bytes, signature: str | None) -> bool:
        """Verify OpenWA webhook signature using HMAC-SHA256."""
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

    def get_status(self) -> dict[str, Any]:
        """Check OpenWA API health."""
        base = super().get_status()
        if not self.is_configured:
            return base
        try:
            response = self._api_call("GET", "/api/health")
            base["api_reachable"] = True
            base["api_version"] = response.get("version")
            base["connected"] = response.get("connected", False)
        except Exception:
            base["api_reachable"] = False
            base["connected"] = False
        return base

    def _api_call(
        self, method: str, path: str, body: bytes | None = None
    ) -> dict:
        """Make an authenticated OpenWA API call using stdlib."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        url = f"{self.config.api_base_url.rstrip('/')}{path}"
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
                "OpenWA API %s %s returned %s: %s",
                method, path, exc.code, error_body[:200],
            )
            try:
                return json.loads(error_body)
            except (json.JSONDecodeError, ValueError):
                raise ConnectionError(
                    f"OpenWA API error {exc.code}: {error_body[:200]}"
                ) from exc
