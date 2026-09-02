"""Calling/Telephony integration provider foundation.

This provider establishes the architectural foundation for future calling
capabilities (outbound calls, inbound events, call status, recordings,
transcription). It appears in the Integrations Manager as "Coming Soon"
until a telephony provider is configured on the KVM.

Future providers may include:
- Asterisk (self-hosted PBX)
- LiveKit (WebRTC)
- Plivo / Twilio (PSTN)
- Custom SIP providers
"""

from __future__ import annotations

from integrations_manager.app.providers.base import (
    BaseProvider,
    IntegrationInfo,
    OAuthConfig,
    TestResult,
)


class CallingProvider(BaseProvider):
    """Calling/telephony capability foundation provider."""

    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="calling",
            name="Calling / Telephony",
            description="Voice calling and telephony capabilities (coming soon)",
            icon="📞",
            auth_type="api_key",
            credential_fields=[
                {
                    "key": "base_url",
                    "label": "Telephony Service URL",
                    "type": "url",
                    "required": True,
                    "description": "URL of the telephony provider (e.g. http://localhost:8088 for Asterisk)",
                },
                {
                    "key": "api_key",
                    "label": "API Key",
                    "type": "password",
                    "required": False,
                    "description": "API authentication key (if required by the provider)",
                },
            ],
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return None

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        base_url = credentials.get("base_url", "").rstrip("/")
        if not base_url:
            return TestResult(
                success=False,
                message="No telephony provider configured yet — coming soon",
            )

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
                return TestResult(
                    success=True,
                    message="Telephony provider is healthy",
                    details={"status": "connected", "provider": "calling"},
                )
        except urllib.error.URLError as e:
            return TestResult(
                success=False,
                message=f"Cannot reach telephony service at {base_url}: {e.reason}",
            )
        except Exception as e:
            return TestResult(
                success=False,
                message=f"Connection test failed: {e}",
            )

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        base_url = credentials.get("base_url", "").rstrip("/")
        if not base_url:
            return {
                "provider": "calling",
                "status": "not_configured",
                "message": "No telephony provider configured yet",
            }

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
                return {"provider": "calling", "status": "connected", "info": data}
        except Exception as e:
            return {"error": str(e), "provider": "calling"}
