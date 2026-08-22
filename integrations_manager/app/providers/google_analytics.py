"""Google Analytics 4 integration provider.

Supports OAuth 2.0 flow for GA4 property discovery and reporting.
"""
from __future__ import annotations

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.config import settings


class GoogleAnalyticsProvider(BaseProvider):
    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="google_analytics",
            name="Google Analytics 4",
            description="Connect GA4 for website analytics, traffic sources, and conversions.",
            icon="📊",
            auth_type="oauth2",
            credential_fields=[
                {"key": "property_id", "label": "GA4 Property ID", "type": "text", "required": False},
            ],
            oauth_scopes=[
                "https://www.googleapis.com/auth/analytics.readonly",
                "https://www.googleapis.com/auth/analytics.manage.users.readonly",
            ],
            oauth_auth_url="https://accounts.google.com/o/oauth2/v2/auth",
            oauth_token_url="https://oauth2.googleapis.com/token",
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return OAuthConfig(
            auth_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=self.info().oauth_scopes,
            redirect_uri=f"{settings.OAUTH_REDIRECT_BASE}/api/oauth/google/callback",
        )

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        access_token = credentials.get("access_token", "")
        property_id = credentials.get("property_id", "")
        refresh_token = credentials.get("refresh_token", "")

        if not access_token and not refresh_token:
            return TestResult(success=False, message="Not authenticated — complete OAuth first")

        # Try to list account summaries
        try:
            url = "https://analyticsadmin.googleapis.com/v1alpha/accountSummaries"
            req = Request(url, headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "GoalOS-Integrations-Manager/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                summaries = data.get("accountSummaries", [])
                return TestResult(
                    success=True,
                    message=f"Connected — {len(summaries)} account(s) found",
                    details={"accounts": summaries},
                )
        except HTTPError as e:
            if e.code == 401:
                return TestResult(success=False, message="Token expired — re-authenticate")
            return TestResult(success=False, message=f"HTTP {e.code}: {e.reason}")
        except (URLError, TimeoutError) as e:
            return TestResult(success=False, message=f"Connection failed: {e}")
        except Exception as e:
            return TestResult(success=False, message=f"Error: {type(e).__name__}")

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        result = await self.test_connection(credentials)
        if result.success:
            return result.details
        return {"error": result.message}
