"""WooCommerce integration: REST API reads and permission-gated writes.

Uses WooCommerce REST API v3 (``/wp-json/wc/v3``) over the shared HTTP
client with Basic auth from consumer key/secret configuration. Reads are
always available when configured; the stock write capability requires
explicit ``WRITE_WEBSITE`` authorization and is never invoked implicitly.
"""

from __future__ import annotations

import base64
from typing import Any, ClassVar
from urllib.parse import urljoin

from app.agents.permissions import Permission
from app.integrations.exceptions import CapabilityUnavailableError
from app.integrations.http_client import HttpClient
from app.integrations.integration_connector import IntegrationConnector


class WooCommerceConnector(IntegrationConnector):
    """WooCommerce store connector for products, orders, and customers."""

    required_env_vars: tuple[str, ...] = (
        "GOALOS_WOO_URL",
        "GOALOS_WOO_CONSUMER_KEY",
        "GOALOS_WOO_CONSUMER_SECRET",
    )
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "woocommerce.products": Permission.READ_WEBSITE,
        "woocommerce.orders": Permission.READ_WEBSITE,
        "woocommerce.customers": Permission.READ_WEBSITE,
        "woocommerce.inventory": Permission.READ_WEBSITE,
        "woocommerce.product.update": Permission.WRITE_WEBSITE,
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        base_url: str | None = None,
        consumer_key: str | None = None,
        consumer_secret: str | None = None,
    ) -> None:
        super().__init__(
            name="woocommerce",
            description="WooCommerce REST API integration",
        )
        self.client = client or HttpClient()
        self.base_url = (base_url or self._env("GOALOS_WOO_URL") or "").rstrip("/")
        self.consumer_key = consumer_key or self._env("GOALOS_WOO_CONSUMER_KEY") or ""
        self.consumer_secret = consumer_secret or self._env("GOALOS_WOO_CONSUMER_SECRET") or ""

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "woocommerce.products",
            "woocommerce.orders",
            "woocommerce.customers",
            "woocommerce.inventory",
            "woocommerce.product.update",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing = [
            name
            for name, value in (
                ("GOALOS_WOO_URL", self.base_url),
                ("GOALOS_WOO_CONSUMER_KEY", self.consumer_key),
                ("GOALOS_WOO_CONSUMER_SECRET", self.consumer_secret),
            )
            if not value
        ]
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "woocommerce.products":
            return self._get("/products", params)
        if capability == "woocommerce.orders":
            return self._get("/orders", params)
        if capability == "woocommerce.customers":
            return self._get("/customers", params)
        if capability == "woocommerce.inventory":
            return self._stock_summary(params)
        if capability == "woocommerce.product.update":
            return self._update_product_stock(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        per_page = int(params.get("per_page") or 20)
        query = {"per_page": per_page}
        if params.get("search"):
            query["search"] = params["search"]
        if params.get("id"):
            path = f"{path}/{params['id']}"
        response = self.client.get(self._url(path), headers=self._headers(), params=query)
        return self._decode_list(response, path)

    def _stock_summary(self, params: dict[str, Any]) -> dict[str, Any]:
        response = self.client.get(
            self._url("/products"),
            headers=self._headers(),
            params={
                "per_page": int(params.get("per_page") or 100),
                "fields": "id,name,stock_quantity,stock_status",
            },
        )
        products = self._json(response.text)
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
        low = [item for item in items if item["stock_status"] == "instock" and (item["stock_quantity"] is None or int(item["stock_quantity"] or 0) <= 5)]
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
        response = self.client.fetch(
            self._url(f"/products/{product_id}"),
            method="PUT",
            headers={**self._headers(), "Content-Type": "application/json"},
            body=self._dumps(payload).encode(),
        )
        product = self._json(response.text)
        return {
            "id": product.get("id"),
            "name": product.get("name"),
            "stock_quantity": product.get("stock_quantity"),
            "stock_status": product.get("stock_status"),
        }

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/wp-json/wc/v3/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        token = base64.b64encode(
            f"{self.consumer_key}:{self.consumer_secret}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}"}

    @staticmethod
    def _json(text: str) -> Any:
        import json

        return json.loads(text)

    @staticmethod
    def _dumps(payload: dict[str, Any]) -> str:
        import json

        return json.dumps(payload)

    def _decode_list(self, response: Any, path: str) -> dict[str, Any]:
        import json

        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            data = []
        return {
            "path": path,
            "total": len(data) if isinstance(data, list) else 0,
            "items": data if isinstance(data, list) else [data],
        }
