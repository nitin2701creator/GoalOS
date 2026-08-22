"""WooCommerce integration provider.

Supports Store URL + Consumer Key + Consumer Secret authentication.
Uses the WooCommerce REST API v3.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from base64 import b64encode
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig


class WooCommerceProvider(BaseProvider):
    def info(self) -> IntegrationInfo:
        return IntegrationInfo(
            slug="woocommerce",
            name="WooCommerce",
            description="Connect to your WooCommerce store for order and product data.",
            icon="🛒",
            auth_type="api_key",
            credential_fields=[
                {"key": "store_url", "label": "Store URL", "type": "url", "required": True},
                {"key": "consumer_key", "label": "Consumer Key", "type": "text", "required": True},
                {"key": "consumer_secret", "label": "Consumer Secret", "type": "password", "required": True},
            ],
        )

    def get_credential_fields(self) -> list[dict]:
        return self.info().credential_fields

    def get_oauth_config(self) -> OAuthConfig | None:
        return None

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        store_url = credentials.get("store_url", "").rstrip("/")
        consumer_key = credentials.get("consumer_key", "")
        consumer_secret = credentials.get("consumer_secret", "")

        if not all([store_url, consumer_key, consumer_secret]):
            return TestResult(success=False, message="Missing required credentials")

        try:
            url = f"{store_url}/wp-json/wc/v3/system_status?consumer_key={consumer_key}&consumer_secret={consumer_secret}"
            req = Request(url, headers={"User-Agent": "GoalOS-Integrations-Manager/1.0"})
            with urlopen(req, timeout=15) as resp:
                data = __import__("json").loads(resp.read().decode())
                return TestResult(
                    success=True,
                    message="Connected successfully",
                    details={
                        "store_name": data.get("store_name", ""),
                        "wc_version": data.get("wc_version", ""),
                        "wordpress_version": data.get("wordpress_version", ""),
                    },
                )
        except HTTPError as e:
            if e.code == 401:
                return TestResult(success=False, message="Authentication failed — check Consumer Key and Secret")
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
