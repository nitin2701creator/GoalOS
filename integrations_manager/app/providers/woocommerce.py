"""WooCommerce integration provider.

Supports Store URL + Consumer Key + Consumer Secret authentication. Uses
the WooCommerce REST API v3. Re-uses the GoalOS store-URL normalization
and connection-candidate helpers so the Integrations Manager behaves
exactly like the app-side ``WooCommerceConnector``.

Honesty contract (mirrors ``app.integrations.woocommerce``):

- ``connected`` is only reported after a real ``system_status`` request
  answered with a valid WooCommerce JSON payload;
- credentials are sent via the ``Authorization`` header (never the query
  string) and never appear in messages or logs;
- failures are classified with the canonical status vocabulary:
  ``invalid_config``, ``auth_failed``, ``unreachable``, ``api_unavailable``.
"""
from __future__ import annotations

import json
from base64 import b64encode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from integrations_manager.app.providers.base import (
    BaseProvider,
    IntegrationInfo,
    OAuthConfig,
    TestResult,
)

from app.integrations.woocommerce import (
    normalize_store_url,
    store_connection_candidates,
)

_API_VERSION = "wc/v3"


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

    def get_connection_state(self, credentials: dict[str, str]) -> str:
        if not credentials:
            return "not_configured"
        if all(
            credentials.get(key)
            for key in ("store_url", "consumer_key", "consumer_secret")
        ):
            return "configured"
        return "not_configured"

    @staticmethod
    def _auth_header(consumer_key: str, consumer_secret: str) -> dict[str, str]:
        token = b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    async def test_connection(self, credentials: dict[str, str]) -> TestResult:
        store_url = credentials.get("store_url", "")
        consumer_key = credentials.get("consumer_key", "")
        consumer_secret = credentials.get("consumer_secret", "")

        if not all([store_url, consumer_key, consumer_secret]):
            return TestResult(
                success=False,
                status="invalid_config",
                message="Missing required credentials",
            )

        try:
            normalize_store_url(store_url)
        except ValueError as exc:
            return TestResult(
                success=False,
                status="invalid_config",
                message=str(exc),
            )

        candidates = store_connection_candidates(store_url.strip())
        last_network_error = ""
        for candidate in candidates:
            api_url = f"{candidate.rstrip('/')}/wp-json/{_API_VERSION}/system_status"
            req = Request(
                api_url,
                headers={
                    "User-Agent": "GoalOS-Integrations-Manager/1.0",
                    **self._auth_header(consumer_key, consumer_secret),
                },
            )
            try:
                with urlopen(req, timeout=15) as resp:
                    body = resp.read().decode()
            except HTTPError as exc:
                status = int(exc.code)
                if status in (401, 403):
                    return TestResult(
                        success=False,
                        status="auth_failed",
                        message="Authentication failed — check Consumer Key and Secret",
                    )
                return TestResult(
                    success=False,
                    status="api_unavailable",
                    message=f"WooCommerce API responded HTTP {status} at {candidate}",
                )
            except (URLError, TimeoutError, OSError) as exc:
                last_network_error = f"connection failed: {exc}"
                continue
            return self._classify_response(body, candidate)

        return TestResult(
            success=False,
            status="unreachable",
            message=last_network_error or "Cannot reach the store",
        )

    @staticmethod
    def _classify_response(body: str, candidate: str) -> TestResult:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            return TestResult(
                success=False,
                status="api_unavailable",
                message=f"Response from {candidate} is not valid WooCommerce JSON",
            )
        if not isinstance(data, dict):
            return TestResult(
                success=False,
                status="api_unavailable",
                message=f"Response from {candidate} is not a WooCommerce payload",
            )
        environment = data.get("environment")
        details: dict[str, str] = {"store_url": candidate, "api_version": _API_VERSION}
        if isinstance(environment, dict):
            for key, detail in (
                ("woocommerce_version", "wc_version"),
                ("wp_version", "wordpress_version"),
                ("site_url", "site_url"),
            ):
                value = environment.get(key)
                if isinstance(value, str) and value:
                    details[detail] = value
        return TestResult(
            success=True,
            status="connected",
            message="Connected successfully",
            details=details,
        )

    async def get_account_info(self, credentials: dict[str, str]) -> dict:
        result = await self.test_connection(credentials)
        if result.success:
            return result.details
        return {"error": result.message}