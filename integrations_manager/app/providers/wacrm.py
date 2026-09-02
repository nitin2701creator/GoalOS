"""WACRM WhatsApp Business API integration provider.

WACRM is the official Meta WhatsApp Business Cloud API integration.
It provides a shared inbox, contacts, conversations, templates,
broadcasts, automations, and a public REST API.

Environment variables:
    GOALOS_WACRM_BASE_URL  — WACRM service URL
    GOALOS_WACRM_API_KEY   — WACRM API key
    WACRM_WEBHOOK_SECRET   — Webhook signature verification secret
"""

from __future__ import annotations

import os

from integrations_manager.app.providers.base import (
    BaseProvider,
    IntegrationInfo,
    OAuthConfig,
    TestResult,
)


class WacrmProvider(BaseProvider):
    """WACRM WhatsApp Business Cloud API integration provider."""

    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="wacrm",
            name="WhatsApp / WACRM",
            description="Official Meta WhatsApp Business Cloud API integration via WACRM",
            icon="📱",
            auth_type="api_key",
            credential_fields=[
                {
                    "key": "base_url",
                    "label": "WACRM Base URL",
                    "type": "url",
                    "required": True,
                    "description": "The URL where WACRM is running (e.g. http://localhost:3000)",
                },
                {
                    "key": "api_key",
                    "label": "API Key",
                    "type": "password",
                    "required": True,
                    "description": "WACRM API key (created in WACRM dashboard → Settings → API keys)",
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
        return None  # WACRM uses API key auth, not OAuth

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        base_url = credentials.get("base_url", "").rstrip("/")
        api_key = credentials.get("api_key", "")

        if not base_url:
            return TestResult(success=False, message="Base URL is required")
        if not api_key:
            return TestResult(success=False, message="API key is required")

        import urllib.request
        import json

        try:
            url = f"{base_url}/api/v1/me"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {api_key}")
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return TestResult(
                    success=True,
                    message="WACRM is healthy and authenticated",
                    details={
                        "status": "connected",
                        "provider": "wacrm",
                        "user": data.get("user", {}).get("email", "authenticated"),
                    },
                )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                return TestResult(
                    success=False,
                    message="WACRM rejected the API key (401 Unauthorized)",
                )
            return TestResult(
                success=False,
                message=f"WACRM returned HTTP {e.code}: {body[:200]}",
            )
        except urllib.error.URLError as e:
            return TestResult(
                success=False,
                message=f"Cannot reach WACRM at {base_url}: {e.reason}",
            )
        except Exception as e:
            return TestResult(
                success=False,
                message=f"Connection test failed: {e}",
            )

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        base_url = credentials.get("base_url", "").rstrip("/")
        api_key = credentials.get("api_key", "")

        if not base_url or not api_key:
            return {"error": "Not configured"}

        import urllib.request
        import json

        try:
            url = f"{base_url}/api/v1/me"
            req = urllib.request.Request(url, method="GET")
            req.add_header("Authorization", f"Bearer {api_key}")
            req.add_header("Accept", "application/json")

            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return {
                    "provider": "wacrm",
                    "user": data.get("user", {}),
                    "status": "connected",
                }
        except Exception as e:
            return {"error": str(e), "provider": "wacrm"}
