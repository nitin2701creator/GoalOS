"""LinkedIn integration provider.

Supports OAuth 2.0 for LinkedIn Page/Person access and analytics.
"""
from __future__ import annotations

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.config import settings


class LinkedInProvider(BaseProvider):
    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="linkedin",
            name="LinkedIn",
            description="Connect LinkedIn for professional networking and content publishing.",
            icon="💼",
            auth_type="oauth2",
            credential_fields=[
                {"key": "organization_id", "label": "Organization ID", "type": "text", "required": False},
            ],
            oauth_scopes=[
                "openid",
                "profile",
                "email",
                "w_member_social",
                "r_organization_social",
                "w_organization_social",
            ],
            oauth_auth_url="https://www.linkedin.com/oauth/v2/authorization",
            oauth_token_url="https://www.linkedin.com/oauth/v2/accessToken",
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return OAuthConfig(
            auth_url="https://www.linkedin.com/oauth/v2/authorization",
            token_url="https://www.linkedin.com/oauth/v2/accessToken",
            scopes=self.info().oauth_scopes,
            redirect_uri=f"{settings.OAUTH_REDIRECT_BASE}/api/oauth/linkedin/callback",
        )

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        access_token = credentials.get("access_token", "")
        if not access_token:
            return TestResult(success=False, message="Not authenticated — complete OAuth first")

        try:
            url = "https://api.linkedin.com/v2/userinfo"
            req = Request(url, headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "GoalOS-Integrations-Manager/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                sub = data.get("sub", "")
                name = data.get("name", "")
                return TestResult(
                    success=True,
                    message=f"Connected as {name}",
                    details={"sub": sub, "name": name},
                )
        except HTTPError as e:
            return TestResult(success=False, message=f"Authentication failed: {e.code}")
        except (URLError, TimeoutError) as e:
            return TestResult(success=False, message=f"Connection failed: {e}")
        except Exception as e:
            return TestResult(success=False, message=f"Error: {type(e).__name__}")

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        result = await self.test_connection(credentials)
        if result.success:
            return result.details
        return {"error": result.message}
