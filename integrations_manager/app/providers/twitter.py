"""X/Twitter integration provider.

Supports OAuth 2.0 (PKCE) for X API v2 — tweet publishing and account metrics.
"""
from __future__ import annotations

from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import json

from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.config import settings


class TwitterProvider(BaseProvider):
    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="twitter",
            name="X / Twitter",
            description="Connect X for tweet publishing and account analytics.",
            icon="🐦",
            auth_type="oauth2",
            credential_fields=[
                {"key": "bearer_token", "label": "Bearer Token", "type": "password", "required": False},
            ],
            oauth_scopes=[
                "tweet.read",
                "tweet.write",
                "users.read",
                "offline.access",
            ],
            oauth_auth_url="https://twitter.com/i/oauth2/authorize",
            oauth_token_url="https://api.twitter.com/2/oauth2/token",
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return OAuthConfig(
            auth_url="https://twitter.com/i/oauth2/authorize",
            token_url="https://api.twitter.com/2/oauth2/token",
            scopes=self.info().oauth_scopes,
            redirect_uri=f"{settings.OAUTH_REDIRECT_BASE}/api/oauth/twitter/callback",
        )

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        access_token = credentials.get("access_token", "")
        bearer_token = credentials.get("bearer_token", "")
        token = access_token or bearer_token
        if not token:
            return TestResult(success=False, message="Not authenticated — complete OAuth first")

        try:
            url = "https://api.twitter.com/2/users/me?user.fields=name,username,public_metrics"
            req = Request(url, headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "GoalOS-Integrations-Manager/1.0",
            })
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                user = data.get("data", {})
                return TestResult(
                    success=True,
                    message=f"Connected as @{user.get('username', 'unknown')}",
                    details={
                        "user_id": user.get("id"),
                        "username": user.get("username"),
                        "name": user.get("name"),
                        "followers": user.get("public_metrics", {}).get("followers_count", 0),
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
