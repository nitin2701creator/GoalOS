"""WhatsApp capability adapter — wraps OpenWA behind GoalOS interfaces.

OpenWA runs as a separate Node.js service exposing a REST API.
GoalOS communicates with it via HTTP, keeping the adapter thin and
provider-neutral at the GoalOS layer.

Environment variables:
    GOALOS_OPENWA_BASE_URL  — OpenWA service URL (e.g. http://localhost:5800)
    GOALOS_OPENWA_API_KEY   — OpenWA API authentication key
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agents.permissions import Permission
from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WhatsAppMessage:
    """Normalized WhatsApp message."""

    message_id: str
    from_number: str
    to_number: str
    body: str
    timestamp: str
    message_type: str = "text"
    media_url: str | None = None
    caption: str | None = None
    conversation_id: str | None = None
    provider: str = "openwa"


@dataclass(frozen=True, slots=True)
class WhatsAppSendRequest:
    """Request to send a WhatsApp message."""

    to_number: str
    body: str
    message_type: str = "text"
    media_url: str | None = None
    caption: str | None = None


@dataclass(frozen=True, slots=True)
class WhatsAppSendResponse:
    """Response from sending a WhatsApp message."""

    success: bool
    message_id: str | None = None
    error: str | None = None
    provider: str = "openwa"


@dataclass(frozen=True, slots=True)
class WhatsAppSession:
    """WhatsApp session status."""

    session_id: str
    status: str
    phone_number: str | None = None
    push_name: str | None = None
    client_name: str | None = None
    adapter: str = "openwa"


@dataclass(frozen=True, slots=True)
class WebhookPayload:
    """Normalized inbound webhook from OpenWA."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    message: WhatsAppMessage | None = None
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# OpenWA Connector
# ---------------------------------------------------------------------------

class OpenWAConnector(BaseConnector):
    """GoalOS connector for OpenWA WhatsApp service.

    Communicates with the OpenWA REST API over HTTP. Does not embed
    OpenWA's Node.js runtime — OpenWA runs as a separate container/service.
    """

    required_env_vars = ("GOALOS_OPENWA_BASE_URL", "OPENWA_API_URL")

    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "whatsapp.send_message": Permission.PUBLISH_SOCIAL,
        "whatsapp.send_media": Permission.PUBLISH_SOCIAL,
        "whatsapp.receive_message": Permission.READ_SOCIAL,
        "whatsapp.list_sessions": Permission.READ_SOCIAL,
        "whatsapp.session_status": Permission.READ_SOCIAL,
    }

    def __init__(self) -> None:
        super().__init__(
            name="openwa",
            description="OpenWA WhatsApp service adapter",
        )

    def get_capabilities(self) -> tuple[str, ...]:
        return tuple(self.CAPABILITY_PERMISSIONS.keys())

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self.CAPABILITY_PERMISSIONS.keys())

    def capability_available(self, capability: str) -> tuple[bool, str]:
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"
        if not self.is_configured:
            return False, "OpenWA not configured — GOALOS_OPENWA_BASE_URL not set"
        return True, "available"

    @property
    def base_url(self) -> str:
        return os.environ.get("GOALOS_OPENWA_BASE_URL", os.environ.get("OPENWA_API_URL", "")).rstrip("/")

    @property
    def api_key(self) -> str:
        return os.environ.get("GOALOS_OPENWA_API_KEY", os.environ.get("OPENWA_AUTH_TOKEN", ""))

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    # -- Lifecycle --

    def connect(self) -> None:
        if not self.is_configured:
            self._set_health(ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "GOALOS_OPENWA_BASE_URL is not set",
            ))
            return
        self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY, "configured"))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "disconnected"))

    def health_check(self) -> ConnectorHealth:
        if not self.is_configured:
            return ConnectorHealth(ConnectorHealthStatus.NOT_CONFIGURED, "not configured")
        try:
            result = self._api_get("/health")
            if result.get("status") == "ok":
                return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "openwa healthy")
            return ConnectorHealth(ConnectorHealthStatus.DEGRADED, f"unexpected: {result}")
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(ConnectorHealthStatus.UNHEALTHY, f"health check failed: {exc}")

    # -- Capability execution --

    def execute(self, capability: str, params: dict[str, Any], *, permissions: set[Permission] | None = None) -> dict[str, Any]:
        """Dispatch a capability call to the OpenWA API."""
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: GOALOS_OPENWA_BASE_URL not set"}
        if capability == "whatsapp.send_message":
            return self._send_message(params)
        elif capability == "whatsapp.send_media":
            return self._send_media(params)
        elif capability == "whatsapp.receive_message":
            return self._receive_messages(params)
        elif capability == "whatsapp.list_sessions":
            return self._list_sessions()
        elif capability == "whatsapp.session_status":
            return self._session_status(params)
        else:
            return {"error": f"unknown capability: {capability}"}

    # -- API operations --

    def _send_message(self, params: dict[str, Any]) -> dict[str, Any]:
        to_number = params.get("to_number", "")
        body = params.get("body", "")
        if not to_number or not body:
            return {"error": "to_number and body are required"}
        try:
            result = self._api_post("/api/sendText", {
                "chatId": to_number,
                "text": body,
            })
            return {
                "success": True,
                "message_id": result.get("key", {}).get("id", ""),
                "provider": "openwa",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenWA send_message failed")
            return {"error": str(exc), "provider": "openwa"}

    def _send_media(self, params: dict[str, Any]) -> dict[str, Any]:
        to_number = params.get("to_number", "")
        media_url = params.get("media_url", "")
        caption = params.get("caption", "")
        if not to_number or not media_url:
            return {"error": "to_number and media_url are required"}
        try:
            result = self._api_post("/api/sendImage", {
                "chatId": to_number,
                "file": media_url,
                "caption": caption,
            })
            return {
                "success": True,
                "message_id": result.get("key", {}).get("id", ""),
                "provider": "openwa",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("OpenWA send_media failed")
            return {"error": str(exc), "provider": "openwa"}

    def _receive_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch recent messages (polling mode)."""
        try:
            result = self._api_get("/api/messages")
            messages = result if isinstance(result, list) else result.get("messages", [])
            normalized = []
            for msg in messages[-50:]:  # last 50 messages
                normalized.append({
                    "message_id": msg.get("id", {}).get("id", ""),
                    "from_number": msg.get("key", {}).get("remoteJid", ""),
                    "body": msg.get("message", {}).get("conversation", "")
                            or msg.get("message", {}).get("extendedTextMessage", {}).get("text", ""),
                    "timestamp": str(msg.get("messageTimestamp", "")),
                    "message_type": "text",
                })
            return {"messages": normalized, "count": len(normalized), "provider": "openwa"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "openwa"}

    def _list_sessions(self) -> dict[str, Any]:
        try:
            result = self._api_get("/api/sessions")
            sessions = result if isinstance(result, list) else result.get("sessions", [])
            return {"sessions": sessions, "count": len(sessions), "provider": "openwa"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "openwa"}

    def _session_status(self, params: dict[str, Any]) -> dict[str, Any]:
        session_id = params.get("session_id", "default")
        try:
            result = self._api_get(f"/api/sessions/{session_id}")
            return {
                "session_id": session_id,
                "status": result.get("status", "unknown"),
                "provider": "openwa",
            }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "openwa"}

    # -- HTTP helpers --

    def _api_get(self, path: str) -> Any:
        return self._request("GET", path)

    def _api_post(self, path: str, data: dict[str, Any]) -> Any:
        return self._request("POST", path, data)

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as resp:
                response_body = resp.read().decode("utf-8")
                return json.loads(response_body)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenWA API error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"OpenWA connection failed: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# WACRM Connector
# ---------------------------------------------------------------------------

class WacrmConnector(BaseConnector):
    """GoalOS connector for WACRM WhatsApp Business API service.

    Communicates with the WACRM REST API over HTTP. Does not embed
    WACRM's Node.js runtime — WACRM runs as a separate container/service.

    Environment variables:
        GOALOS_WACRM_BASE_URL  — WACRM service URL (e.g. http://localhost:3000)
        GOALOS_WACRM_API_KEY   — WACRM API authentication key
    """

    required_env_vars = ("GOALOS_WACRM_BASE_URL", "WACRM_API_URL")

    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "whatsapp.send_message": Permission.PUBLISH_SOCIAL,
        "whatsapp.send_media": Permission.PUBLISH_SOCIAL,
        "whatsapp.receive_message": Permission.READ_SOCIAL,
        "whatsapp.list_contacts": Permission.READ_SOCIAL,
        "whatsapp.list_conversations": Permission.READ_SOCIAL,
        "whatsapp.send_template": Permission.PUBLISH_SOCIAL,
    }

    def __init__(self) -> None:
        super().__init__(
            name="wacrm",
            description="WACRM WhatsApp Business Cloud API adapter",
        )

    def get_capabilities(self) -> tuple[str, ...]:
        return tuple(self.CAPABILITY_PERMISSIONS.keys())

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self.CAPABILITY_PERMISSIONS.keys())

    @property
    def base_url(self) -> str:
        return os.environ.get("GOALOS_WACRM_BASE_URL", os.environ.get("WACRM_API_URL", "")).rstrip("/")

    @property
    def api_key(self) -> str:
        return os.environ.get("GOALOS_WACRM_API_KEY", os.environ.get("WACRM_API_KEY", ""))

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    # -- Lifecycle --

    def connect(self) -> None:
        if not self.is_configured:
            self._set_health(ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "GOALOS_WACRM_BASE_URL is not set",
            ))
            return
        self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY, "configured"))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "disconnected"))

    def health_check(self) -> ConnectorHealth:
        if not self.is_configured:
            return ConnectorHealth(ConnectorHealthStatus.NOT_CONFIGURED, "not configured")
        try:
            result = self._api_get("/api/v1/me")
            if result.get("status") == "success" or "user" in result:
                return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "wacrm healthy")
            return ConnectorHealth(ConnectorHealthStatus.DEGRADED, f"unexpected: {result}")
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(ConnectorHealthStatus.UNHEALTHY, f"health check failed: {exc}")

    # -- Capability execution --

    def execute(self, capability: str, params: dict[str, Any], *, permissions: set[Permission] | None = None) -> dict[str, Any]:
        """Dispatch a capability call to the WACRM API."""
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: GOALOS_WACRM_BASE_URL not set"}
        if capability == "whatsapp.send_message":
            return self._send_message(params)
        elif capability == "whatsapp.send_media":
            return self._send_media(params)
        elif capability == "whatsapp.receive_message":
            return self._receive_messages(params)
        elif capability == "whatsapp.list_contacts":
            return self._list_contacts(params)
        elif capability == "whatsapp.list_conversations":
            return self._list_conversations(params)
        elif capability == "whatsapp.send_template":
            return self._send_template(params)
        else:
            return {"error": f"unknown capability: {capability}"}

    # -- API operations --

    def _send_message(self, params: dict[str, Any]) -> dict[str, Any]:
        to_number = params.get("to_number", "")
        body = params.get("body", "")
        if not to_number or not body:
            return {"error": "to_number and body are required"}
        try:
            result = self._api_post("/api/v1/messages", {
                "to": to_number,
                "type": "text",
                "text": {"body": body},
            })
            return {
                "success": True,
                "message_id": result.get("id", ""),
                "provider": "wacrm",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("WACRM send_message failed")
            return {"error": str(exc), "provider": "wacrm"}

    def _send_media(self, params: dict[str, Any]) -> dict[str, Any]:
        to_number = params.get("to_number", "")
        media_url = params.get("media_url", "")
        caption = params.get("caption", "")
        if not to_number or not media_url:
            return {"error": "to_number and media_url are required"}
        try:
            result = self._api_post("/api/v1/messages", {
                "to": to_number,
                "type": "image",
                "image": {"link": media_url, "caption": caption},
            })
            return {
                "success": True,
                "message_id": result.get("id", ""),
                "provider": "wacrm",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("WACRM send_media failed")
            return {"error": str(exc), "provider": "wacrm"}

    def _receive_messages(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._api_get("/api/v1/messages")
            messages = result.get("messages", []) if isinstance(result, dict) else result
            return {"messages": messages, "count": len(messages), "provider": "wacrm"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "wacrm"}

    def _list_contacts(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._api_get("/api/v1/contacts")
            contacts = result.get("contacts", []) if isinstance(result, dict) else result
            return {"contacts": contacts, "count": len(contacts), "provider": "wacrm"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "wacrm"}

    def _list_conversations(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._api_get("/api/v1/conversations")
            conversations = result.get("conversations", []) if isinstance(result, dict) else result
            return {"conversations": conversations, "count": len(conversations), "provider": "wacrm"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "wacrm"}

    def _send_template(self, params: dict[str, Any]) -> dict[str, Any]:
        to_number = params.get("to_number", "")
        template_name = params.get("template_name", "")
        language = params.get("language", "en")
        if not to_number or not template_name:
            return {"error": "to_number and template_name are required"}
        try:
            result = self._api_post("/api/v1/messages", {
                "to": to_number,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language},
                },
            })
            return {
                "success": True,
                "message_id": result.get("id", ""),
                "provider": "wacrm",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("WACRM send_template failed")
            return {"error": str(exc), "provider": "wacrm"}

    # -- HTTP helpers --

    def _api_get(self, path: str) -> Any:
        return self._request("GET", path)

    def _api_post(self, path: str, data: dict[str, Any]) -> Any:
        return self._request("POST", path, data)

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as resp:
                response_body = resp.read().decode("utf-8")
                return json.loads(response_body)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"WACRM API error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"WACRM connection failed: {exc.reason}") from exc
