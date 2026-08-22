"""Reddit integration provider.

Supports OAuth 2.0 for Reddit account access and post submission.
"""
from __future__ import annotations

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from base64 import b64encode
import json

from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.config import settings


class RedditProvider(BaseProvider):
    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="reddit",
            name="Reddit",
            description="Connect Reddit for subreddit engagement and content posting.",
            icon="🟠",
            auth_type="oauth2",
            credential_fields=[],
            oauth_scopes=["identity", "read", "submit", "history"],
            oauth_auth_url="https://www.reddit.com/api/v1/authorize",
            oauth_token_url="https://www.reddit.com/api/v1/access_token",
        )

    def get_credential_fields(self) -> list[dict]:
        return []

    def get_oauth_config(self) -> OAuthConfig | None:
        return OAuthConfig(
            auth_url="https://www.reddit.com/api/v1/authorize",
            token_url="https://www.reddit.com/api/v1/access_token",
            scopes=self.info().oauth_scopes,
            redirect_uri=f"{settings.OAUTH_REDIRECT_BASE}/api/oauth/reddit/callback",
        )

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        access_token = credentials.get("access_token", "")
        if not access_token:
            return TestResult(success=False, message="Not authenticated — complete OAuth first")

        try:
            url = "https://oauth.reddit.com/api/v1/me"
            req = Request(url, headers={
                "Authorization": f"Bearer {access_token}",
                "User-Agent": "GoalOS-Integrations-Manager/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                return TestResult(
                    success=True,
                    message=f"Connected as u/{data.get('name', 'unknown')}",
                    details={
                        "username": data.get("name"),
                        "link_karma": data.get("link_karma", 0),
                        "comment_karma": data.get("comment_karma", 0),
                    },
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
