"""WooCommerce integration: REST API reads and permission-gated writes.

Uses the WooCommerce REST API (default ``wc/v3``) over the shared HTTP
client with Basic auth from consumer key/secret configuration. Supports
products, orders, customers, categories, sales reports, variations, and
inventory. Reads are available when configured; every write requires
explicit ``WRITE_WEBSITE`` authorization and is never invoked implicitly.

Configuration accepts ``WOOCOMMERCE_URL`` / ``WOOCOMMERCE_CONSUMER_KEY`` /
``WOOCOMMERCE_CONSUMER_SECRET`` (plus optional ``WOOCOMMERCE_API_VERSION``)
with the legacy ``GOALOS_WOO_*`` names as fallbacks.

Honesty contract:

- Missing configuration reports ``Not Configured``.
- HTTP 401/403 maps to :class:`AuthenticationError` (``AUTHENTICATION_FAILED``).
- HTTP 429 maps to :class:`RateLimitError` (``RATE_LIMITED``).
- Other failures and malformed responses raise structured errors.
- Credentials are never logged and never included in execution output.
"""

from __future__ import annotations

import base64
import json
from typing import Any, ClassVar
from urllib.parse import urljoin

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

_READ_CAPABILITIES = frozenset(
    {
        "woocommerce.health",
        "woocommerce.products",
        "woocommerce.orders",
        "woocommerce.customers",
        "woocommerce.inventory",
        "woocommerce.list_products",
        "woocommerce.get_product",
        "woocommerce.list_orders",
        "woocommerce.get_order",
        "woocommerce.list_customers",
        "woocommerce.get_customer",
        "woocommerce.list_categories",
        "woocommerce.get_sales_summary",
        "woocommerce.list_product_variations",
    }
)

#: Capability → REST path for list-style operations.
_LIST_PATHS: dict[str, str] = {
    "woocommerce.products": "/products",
    "woocommerce.orders": "/orders",
    "woocommerce.customers": "/customers",
    "woocommerce.list_products": "/products",
    "woocommerce.list_orders": "/orders",
    "woocommerce.list_customers": "/customers",
    "woocommerce.list_categories": "/products/categories",
}


class WooCommerceConnector(IntegrationConnector):
    """WooCommerce store connector for products, orders, and customers."""

    required_env_vars: tuple[str, ...] = (
        "GOALOS_WOO_URL",
        "GOALOS_WOO_CONSUMER_KEY",
        "GOALOS_WOO_CONSUMER_SECRET",
    )
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        capability: (
            Permission.READ_WEBSITE
            if capability in _READ_CAPABILITIES
            else Permission.WRITE_WEBSITE
        )
        for capability in (
            "woocommerce.health",
            "woocommerce.products",
            "woocommerce.orders",
            "woocommerce.customers",
            "woocommerce.inventory",
            "woocommerce.product.update",
            "woocommerce.list_products",
            "woocommerce.get_product",
            "woocommerce.create_product",
            "woocommerce.update_product",
            "woocommerce.list_orders",
            "woocommerce.get_order",
            "woocommerce.update_order",
            "woocommerce.list_customers",
            "woocommerce.get_customer",
            "woocommerce.list_categories",
            "woocommerce.get_sales_summary",
            "woocommerce.list_product_variations",
            "woocommerce.update_inventory",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        base_url: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
        api_version: str | None = None,
    ) -> None:
        super().__init__(
            name="woocommerce",
            description="WooCommerce REST API integration",
        )
        self.client = client or HttpClient()
        self.base_url = (
            base_url
            or self._env("WOOCOMMERCE_URL")
            or self._env("GOALOS_WOO_URL")
            or ""
        ).rstrip("/")
        self.consumer_key = (
            consumer_key
            or self._env("WOOCOMMERCE_CONSUMER_KEY")
            or self._env("GOALOS_WOO_CONSUMER_KEY")
            or ""
        )
        self.consumer_secret = (
            consumer_secret
            or self._env("WOOCOMMERCE_CONSUMER_SECRET")
            or self._env("GOALOS_WOO_CONSUMER_SECRET")
            or ""
        )
        self.api_version = (
            api_version
            or self._env("WOOCOMMERCE_API_VERSION")
            or "wc/v3"
        ).strip("/")

    def _capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(self.CAPABILITY_PERMISSIONS))

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing: list[str] = []
        if not self.base_url:
            missing.append("GOALOS_WOO_URL (or WOOCOMMERCE_URL)")
        if not self.consumer_key:
            missing.append("GOALOS_WOO_CONSUMER_KEY (or WOOCOMMERCE_CONSUMER_KEY)")
        if not self.consumer_secret:
            missing.append("GOALOS_WOO_CONSUMER_SECRET (or WOOCOMMERCE_CONSUMER_SECRET)")
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "woocommerce.health":
            return self._health()
        if capability in _LIST_PATHS:
            return self._list(_LIST_PATHS[capability], params)
        if capability == "woocommerce.get_product":
            return self._get("/products", params)
        if capability == "woocommerce.get_order":
            return self._get("/orders", params)
        if capability == "woocommerce.get_customer":
            return self._get("/customers", params)
        if capability == "woocommerce.create_product":
            return self._create("/products", params)
        if capability == "woocommerce.update_product":
            return self._update("/products", params)
        if capability == "woocommerce.update_order":
            return self._update("/orders", params)
        if capability == "woocommerce.get_sales_summary":
            return self._sales_summary(params)
        if capability == "woocommerce.list_product_variations":
            product_id = params.get("product_id")
            if not product_id:
                raise ValueError("product_id is required for woocommerce.list_product_variations")
            return self._list(f"/products/{product_id}/variations", params)
        if capability in ("woocommerce.inventory",):
            return self._stock_summary(params)
        if capability in ("woocommerce.update_inventory", "woocommerce.product.update"):
            return self._update_product_stock(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        status, message = self._configuration_status()
        return {
            "integration": "woocommerce",
            "status": status.value,
            "configured": status.value == "Healthy",
            "message": message,
        }

    def _list(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {"per_page": int(params.get("per_page") or 20)}
        if params.get("search"):
            query["search"] = params["search"]
        if params.get("status"):
            query["status"] = params["status"]
        if params.get("id"):
            path = f"{path}/{params['id']}"
        response = self._request("GET", self._url(path), params=query)
        data = self._json_list(response, path)
        return {"path": path, "total": len(data), "items": data}

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params.get("id") or params.get("object_id")
        if not record_id:
            raise ValueError(f"id is required for {path}")
        response = self._request("GET", self._url(f"{path}/{record_id}"))
        data = self._json_list(response, path)
        item = data[0] if data else {}
        return {"path": path, "id": str(record_id), "item": item}

    def _create(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = params.get("fields") or {
            key: value
            for key, value in params.items()
            if key not in ("fields", "id", "object_id")
        }
        if not payload:
            raise ValueError("fields are required to create a record")
        response = self._request(
            "POST",
            self._url(path),
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        item = self._json_item(response, path)
        return {"path": path, "created": True, "item": item}

    def _update(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        record_id = params.get("id") or params.get("object_id")
        if not record_id:
            raise ValueError(f"id is required to update {path}")
        payload = params.get("fields") or {
            key: value
            for key, value in params.items()
            if key not in ("fields", "id", "object_id")
        }
        response = self._request(
            "PUT",
            self._url(f"{path}/{record_id}"),
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        item = self._json_item(response, path)
        return {"path": path, "updated": True, "id": str(record_id), "item": item}

    def _sales_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {"period": params.get("period") or "month"}
        if params.get("date_min"):
            query["date_min"] = params["date_min"]
        if params.get("date_max"):
            query["date_max"] = params["date_max"]
        response = self._request("GET", self._url("/reports/sales"), params=query)
        data = self._json_list(response, "/reports/sales")
        return {"reports": data}

    def _stock_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        response = self._request(
            "GET",
            self._url("/products"),
            params={
                "per_page": int(params.get("per_page") or 100),
                "fields": "id,name,stock_quantity,stock_status",
            },
        )
        products = self._json_list(response, "/products")
        items = [
            {
                "id": product.get("id"),
                "name": product.get("name"),
                "stock_quantity": product.get("stock_quantity"),
                "stock_status": product.get("stock_status"),
            }
            for product in products
            if isinstance(product, dict)
        ]
        low = [
            item
            for item in items
            if item["stock_status"] == "instock"
            and (
                item["stock_quantity"] is None
                or int(item["stock_quantity"] or 0) <= 5
            )
        ]
        return {"total": len(items), "items": items, "low_stock": low}

    def _update_product_stock(self, params: dict[str, Any]) -> dict[str, Any]:
        product_id = params.get("product_id")
        if not product_id:
            raise ValueError("product_id is required for stock updates")
        payload: dict[str, Any] = {}
        if params.get("stock_quantity") is not None:
            payload["stock_quantity"] = int(params["stock_quantity"])
        if params.get("stock_status"):
            payload["stock_status"] = params["stock_status"]
        response = self._request(
            "PUT",
            self._url(f"/products/{product_id}"),
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        product = self._json_item(response, "/products")
        return {
            "id": product.get("id"),
            "name": product.get("name"),
            "stock_quantity": product.get("stock_quantity"),
            "stock_status": product.get("stock_status"),
        }

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/wp-json/{self.api_version}/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.consumer_key}:{self.consumer_secret}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}"}

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue one request with stable error mapping."""
        try:
            return self.client.fetch(
                url,
                method=method,
                headers={**self._headers(), **(headers or {})},
                body=body,
                params=params,
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status in (401, 403):
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: WooCommerce returned HTTP {status} "
                    f"at {exc.url} (check consumer key/secret)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: WooCommerce returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"WooCommerce API error: HTTP {status} at {exc.url}"
            ) from exc

    def _json_list(self, response: Any, path: str) -> list[dict[str, Any]]:
        """Parse a WooCommerce JSON body into a list, mapping failures."""
        status = int(getattr(response, "status", 200) or 200)
        if status in (401, 403):
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: WooCommerce returned HTTP {status} at {path}"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: WooCommerce returned HTTP 429 at {path}")
        if status >= 400:
            raise ConnectorError(
                f"WooCommerce API error: HTTP {status} at {path}: "
                f"{self._error_text(response.text)}"
            )
        try:
            data = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from WooCommerce at {path}: "
                "response body is not valid JSON"
            ) from exc
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
        return []

    def _json_item(self, response: Any, path: str) -> dict[str, Any]:
        items = self._json_list(response, path)
        return items[0] if items else {}

    @staticmethod
    def _error_text(text: str) -> str:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text[:300]
        if isinstance(payload, dict):
            message = payload.get("message")
            if message:
                return str(message)[:300]
            code = payload.get("code")
            if code:
                return str(code)[:300]
        return text[:300]
