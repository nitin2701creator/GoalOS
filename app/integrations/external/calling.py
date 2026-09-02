"""Calling/Telephony capability foundation for GoalOS.

This connector provides the architectural foundation for future calling
capabilities (outbound calls, inbound call events, call status, recordings,
transcription, history). Currently reports as "coming soon" when no
provider is configured, but the capability contract is established so
future telephony providers can be plugged in without redesigning the
integration layer.

Environment variables:
    GOALOS_CALLING_BASE_URL  — Future telephony service URL
    GOALOS_CALLING_API_KEY   — Future telephony API key
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.agents.permissions import Permission
from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus

logger = logging.getLogger(__name__)


class CallingConnector(BaseConnector):
    """GoalOS connector for calling/telephony capabilities.

    Currently a foundation stub. Future providers (Asterisk, LiveKit,
    Plivo, Twilio) will be integrated through this connector once the
    calling infrastructure is deployed on the KVM.
    """

    required_env_vars = ()  # No required vars — this is a foundation

    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "calling.outbound_call": Permission.EXECUTE_AUTOMATION,
        "calling.inbound_events": Permission.READ_SOCIAL,
        "calling.call_status": Permission.READ_SOCIAL,
        "calling.recording_metadata": Permission.READ_SOCIAL,
        "calling.transcription": Permission.READ_SOCIAL,
        "calling.call_history": Permission.READ_SOCIAL,
    }

    def __init__(self) -> None:
        super().__init__(
            name="calling",
            description="Calling/telephony capability foundation (coming soon)",
        )

    def get_capabilities(self) -> tuple[str, ...]:
        return tuple(self.CAPABILITY_PERMISSIONS.keys())

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self.CAPABILITY_PERMISSIONS.keys())

    @property
    def base_url(self) -> str:
        return os.environ.get("GOALOS_CALLING_BASE_URL", "").rstrip("/")

    @property
    def api_key(self) -> str:
        return os.environ.get("GOALOS_CALLING_API_KEY", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    # -- Lifecycle --

    def connect(self) -> None:
        if not self.is_configured:
            self._set_health(ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "No calling provider configured — coming soon",
            ))
            return
        self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY, "configured"))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "disconnected"))

    def health_check(self) -> ConnectorHealth:
        if not self.is_configured:
            return ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "Calling provider not configured — capability coming soon",
            )
        try:
            from urllib.request import Request, urlopen
            url = f"{self.base_url}/health"
            req = Request(url, method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urlopen(req, timeout=10) as resp:
                return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "calling provider healthy")
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(ConnectorHealthStatus.UNHEALTHY, f"health check failed: {exc}")

    # -- Capability execution --

    def execute(self, capability: str, params: dict[str, Any], *, permissions: set[Permission] | None = None) -> dict[str, Any]:
        """Dispatch a capability call to the calling provider."""
        if not self.is_configured:
            return {
                "error": "INTEGRATION_NOT_CONFIGURED: No calling provider configured",
                "capability": capability,
                "status": "coming_soon",
            }

        if capability == "calling.outbound_call":
            return self._outbound_call(params)
        elif capability == "calling.call_status":
            return self._call_status(params)
        elif capability == "calling.call_history":
            return self._call_history(params)
        elif capability in ("calling.inbound_events", "calling.recording_metadata", "calling.transcription"):
            return {
                "error": f"Capability '{capability}' is not yet implemented",
                "status": "coming_soon",
            }
        else:
            return {"error": f"unknown capability: {capability}"}

    def _outbound_call(self, params: dict[str, Any]) -> dict[str, Any]:
        to_number = params.get("to_number", "")
        if not to_number:
            return {"error": "to_number is required"}
        try:
            from urllib.request import Request, urlopen
            import json
            url = f"{self.base_url}/api/v1/calls"
            data = json.dumps({"to": to_number, "from": params.get("from_number", "")}).encode()
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            req = Request(url, data=data, headers=headers, method="POST")
            with urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return {"success": True, "call_id": result.get("call_id", ""), "provider": "calling"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "calling"}

    def _call_status(self, params: dict[str, Any]) -> dict[str, Any]:
        call_id = params.get("call_id", "")
        if not call_id:
            return {"error": "call_id is required"}
        try:
            from urllib.request import Request, urlopen
            import json
            url = f"{self.base_url}/api/v1/calls/{call_id}"
            req = Request(url, method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                return {"call_id": call_id, "status": result.get("status", "unknown"), "provider": "calling"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "calling"}

    def _call_history(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            from urllib.request import Request, urlopen
            import json
            url = f"{self.base_url}/api/v1/calls"
            req = Request(url, method="GET")
            if self.api_key:
                req.add_header("Authorization", f"Bearer {self.api_key}")
            with urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode())
                calls = result.get("calls", []) if isinstance(result, dict) else result
                return {"calls": calls, "count": len(calls), "provider": "calling"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "provider": "calling"}
