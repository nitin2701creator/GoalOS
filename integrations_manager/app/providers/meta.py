"""Meta/Facebook/Instagram integration provider.

Supports OAuth 2.0 for Facebook Pages, Instagram Business accounts, and analytics.
"""
from __future__ import annotations

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.config import settings


class MetaProvider(BaseProvider):
    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="meta",
            name="Meta / Facebook",
            description="Connect Facebook Pages and Instagram Business accounts.",
            icon="📘",
            auth_type="oauth2",
            credential_fields=[
                {"key": "page_access_token", "label": "Page Access Token", "type": "password", "required": False},
            ],
            oauth_scopes=[
                "pages_show_list",
                "pages_read_engagement",
                "pages_manage_posts",
                "instagram_basic",
                "instagram_content_publish",
            ],
            oauth_auth_url="https://www.facebook.com/v19.0/dialog/oauth",
            oauth_token_url="https://graph.facebook.com/v19.0/oauth/access_token",
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return OAuthConfig(
            auth_url="https://www.facebook.com/v19.0/dialog/oauth",
            token_url="https://graph.facebook.com/v19.0/oauth/access_token",
            scopes=self.info().oauth_scopes,
            redirect_uri=f"{settings.OAUTH_REDIRECT_BASE}/api/oauth/meta/callback",
        )

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        token = credentials.get("access_token") or credentials.get("page_access_token", "")
        if not token:
            return TestResult(success=False, message="Not authenticated — complete OAuth first")

        try:
            url = f"https://graph.facebook.com/v19.0/me?fields=name,id&access_token={token}"
            req = Request(url, headers={"User-Agent": "GoalOS-Integrations-Manager/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                return TestResult(
                    success=True,
                    message=f"Connected as {data.get('name', 'Unknown')}",
                    details={"user_id": data.get("id"), "name": data.get("name")},
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
