"""OpenWA WhatsApp integration provider for the Integrations Manager.

OpenWA is a WhatsApp Web gateway that provides an unofficial but
self-hosted WhatsApp integration. GoalOS communicates with it via
HTTP REST API.

Environment variables:
    GOALOS_OPENWA_BASE_URL  — OpenWA service URL
    GOALOS_OPENWA_API_KEY   — OpenWA API key
    OPENWA_WEBHOOK_SECRET   — Webhook signature verification secret
"""

from __future__ import annotations

import os

from integrations_manager.app.providers.base import (
    BaseProvider,
    IntegrationInfo,
    OAuthConfig,
    TestResult,
)


class OpenWAProvider(BaseProvider):
    """OpenWA WhatsApp Web integration provider."""

    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="openwa",
            name="WhatsApp / OpenWA",
            description="WhatsApp Web gateway for sending and receiving messages via OpenWA",
            icon="💬",
            auth_type="api_key",
            credential_fields=[
                {
                    "key": "base_url",
                    "label": "OpenWA Base URL",
                    "type": "url",
                    "required": True,
                    "description": "The URL where OpenWA is running (e.g. http://localhost:5800)",
                },
                {
                    "key": "api_key",
                    "label": "API Key",
                    "type": "password",
                    "required": False,
                    "description": "API authentication key (if configured on OpenWA)",
                },
                {
                    "key": "webhook_secret",
                    "label": "Webhook Secret",
                    "type": "password",
                    "required": False,
                    "description": "HMAC-SHA256 secret for webhook signature verification",
                },
            ],
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return None  # OpenWA uses API key auth, not OAuth

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        base_url = credentials.get("base_url", "").rstrip("/")
        if not base_url:
            return TestResult(success=False, message="Base URL is required")

        import urllib.request
        import json

        try:
            url = f"{base_url}/health"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")

            api_key = credentials.get("api_key", "")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("status") == "ok":
                    return TestResult(
                        success=True,
                        message="OpenWA is healthy and connected",
                        details={"status": "connected", "provider": "openwa"},
                    )
                return TestResult(
                    success=False,
                    message=f"OpenWA returned unexpected status: {data}",
                    details=data,
                )
        except urllib.error.URLError as e:
            return TestResult(
                success=False,
                message=f"Cannot reach OpenWA at {base_url}: {e.reason}",
            )
        except Exception as e:
            return TestResult(
                success=False,
                message=f"Connection test failed: {e}",
            )

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        base_url = credentials.get("base_url", "").rstrip("/")
        if not base_url:
            return {"error": "Base URL not configured"}

        import urllib.request
        import json

        try:
            url = f"{base_url}/api/sessions"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Accept", "application/json")

            api_key = credentials.get("api_key", "")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                sessions = data if isinstance(data, list) else data.get("sessions", [])
                return {
                    "provider": "openwa",
                    "sessions": len(sessions),
                    "status": "connected",
                }
        except Exception as e:
            return {"error": str(e), "provider": "openwa"}
