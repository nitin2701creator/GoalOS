"""Tests for the extended WooCommerce connector.

Covers the full product/order/customer/category/sales/variation/inventory
capability surface, write-permission gates, stable error mapping (auth
failure, rate limiting), and the ``WOOCOMMERCE_*`` env aliases. Never
touches a real store.
"""

from __future__ import annotations

import json

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient
from app.integrations.woocommerce import WooCommerceConnector
from tests.integration_helpers import FakeResponse

PRODUCT = {"id": 1, "name": "Capsule", "price": "19.99", "stock_quantity": 4, "stock_status": "instock"}
ORDER = {"id": 100, "status": "processing", "total": "59.97"}
CUSTOMER = {"id": 7, "email": "buyer@example.com", "first_name": "Jane"}
CATEGORY = {"id": 3, "name": "Wellness"}
SALES = {"total_sales": "1200.00", "total_orders": 42}


def _opener(routes=None, *, default_payload=None, default_status: int = 200):
    routes = routes or {}
    call_log: list[tuple[str, str]] = []

    def opener(request, timeout=None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        call_log.append((method, url))
        payload = None
        status = None
        for (route_method, suffix), routed in routes.items():
            if route_method == method and suffix in url:
                if isinstance(routed, tuple) and len(routed) == 2 and isinstance(routed[0], int):
                    status, payload = routed
                else:
                    payload = routed
                break
        if payload is None:
            payload = default_payload
        if status is None:
            status = default_status
        body = b"" if payload is None else json.dumps(payload).encode()
        return FakeResponse(body, url, status=status, content_type="application/json")

    opener.calls = call_log
    return opener


def _connector(opener, *, base_url: str = "https://shop.example.com") -> WooCommerceConnector:
    return WooCommerceConnector(
        client=HttpClient(opener=opener),
        base_url=base_url,
        consumer_key="ck",
        consumer_secret="cs",
    )


def test_woocommerce_list_and_get_products() -> None:
    opener = _opener(
        {
            ("GET", "/products/1"): PRODUCT,
            ("GET", "/products"): [PRODUCT],
        }
    )
    connector = _connector(opener)

    listed = connector.execute("woocommerce.list_products", {"per_page": 5}, permissions={Permission.READ_WEBSITE})
    assert listed["items"][0]["name"] == "Capsule"

    single = connector.execute("woocommerce.get_product", {"id": 1}, permissions={Permission.READ_WEBSITE})
    assert single["item"]["id"] == 1


def test_woocommerce_legacy_capabilities_still_work() -> None:
    opener = _opener({("GET", "/orders"): [ORDER]})
    connector = _connector(opener)
    orders = connector.execute("woocommerce.orders", {}, permissions={Permission.READ_WEBSITE})
    assert orders["items"][0]["status"] == "processing"


def test_woocommerce_create_product_requires_write() -> None:
    opener = _opener({("POST", "/products"): (201, {**PRODUCT, "id": 2})})
    connector = _connector(opener)

    with pytest.raises(PermissionDeniedError, match="WRITE_WEBSITE"):
        connector.execute(
            "woocommerce.create_product",
            {"fields": {"name": "New Product", "regular_price": "9.99"}},
            permissions={Permission.READ_WEBSITE},
        )

    created = connector.execute(
        "woocommerce.create_product",
        {"fields": {"name": "New Product", "regular_price": "9.99"}},
        permissions={Permission.READ_WEBSITE, Permission.WRITE_WEBSITE},
    )
    assert created["created"] is True
    method, url = opener.calls[0]
    assert method == "POST"
    assert url.endswith("/wp-json/wc/v3/products")


def test_woocommerce_update_product_and_order() -> None:
    opener = _opener(
        {
            ("PUT", "/products/1"): {**PRODUCT, "regular_price": "15.99"},
            ("PUT", "/orders/100"): {**ORDER, "status": "completed"},
        }
    )
    connector = _connector(opener)

    product = connector.execute(
        "woocommerce.update_product",
        {"id": 1, "fields": {"regular_price": "15.99"}},
        permissions={Permission.READ_WEBSITE, Permission.WRITE_WEBSITE},
    )
    assert product["updated"] is True

    order = connector.execute(
        "woocommerce.update_order",
        {"id": 100, "fields": {"status": "completed"}},
        permissions={Permission.READ_WEBSITE, Permission.WRITE_WEBSITE},
    )
    assert order["updated"] is True


def test_woocommerce_customers_and_categories() -> None:
    opener = _opener(
        {
            ("GET", "/customers/7"): CUSTOMER,
            ("GET", "/customers"): [CUSTOMER],
            ("GET", "/products/categories"): [CATEGORY],
        }
    )
    connector = _connector(opener)

    customers = connector.execute("woocommerce.list_customers", {}, permissions={Permission.READ_WEBSITE})
    assert customers["items"][0]["email"] == "buyer@example.com"

    single = connector.execute("woocommerce.get_customer", {"id": 7}, permissions={Permission.READ_WEBSITE})
    assert single["item"]["first_name"] == "Jane"

    categories = connector.execute("woocommerce.list_categories", {}, permissions={Permission.READ_WEBSITE})
    assert categories["items"][0]["name"] == "Wellness"


def test_woocommerce_sales_summary() -> None:
    opener = _opener({("GET", "/reports/sales"): [SALES]})
    connector = _connector(opener)

    result = connector.execute(
        "woocommerce.get_sales_summary", {"period": "month"},
        permissions={Permission.READ_WEBSITE},
    )
    assert result["reports"][0]["total_sales"] == "1200.00"


def test_woocommerce_product_variations() -> None:
    opener = _opener({("GET", "/products/1/variations"): [{"id": 11, "sku": "CAP-M"}]})
    connector = _connector(opener)

    result = connector.execute(
        "woocommerce.list_product_variations", {"product_id": 1},
        permissions={Permission.READ_WEBSITE},
    )
    assert result["items"][0]["sku"] == "CAP-M"


def test_woocommerce_update_inventory() -> None:
    opener = _opener({("PUT", "/products/1"): {**PRODUCT, "stock_quantity": 9}})
    connector = _connector(opener)

    result = connector.execute(
        "woocommerce.update_inventory",
        {"product_id": 1, "stock_quantity": 9},
        permissions={Permission.READ_WEBSITE, Permission.WRITE_WEBSITE},
    )
    assert result["stock_quantity"] == 9


def test_woocommerce_auth_failure_is_distinct() -> None:
    opener = _opener(default_status=401, default_payload={"code": "woocommerce_rest_authentication_error"})
    connector = _connector(opener)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute("woocommerce.list_products", {}, permissions={Permission.READ_WEBSITE})


def test_woocommerce_rate_limit_is_distinct() -> None:
    opener = _opener(default_status=429, default_payload={"code": "rate_limited"})
    connector = _connector(opener)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute("woocommerce.list_products", {}, permissions={Permission.READ_WEBSITE})


def test_woocommerce_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOALOS_WOO_URL", raising=False)
    monkeypatch.delenv("GOALOS_WOO_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("GOALOS_WOO_CONSUMER_SECRET", raising=False)
    monkeypatch.setenv("WOOCOMMERCE_URL", "https://alias.shop.example")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "alias-ck")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "alias-cs")
    monkeypatch.setenv("WOOCOMMERCE_API_VERSION", "wc/v2")
    connector = WooCommerceConnector(client=HttpClient())
    assert connector.is_configured
    assert connector.base_url == "https://alias.shop.example"
    assert connector.api_version == "wc/v2"


def test_woocommerce_health_check_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WOOCOMMERCE_URL", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_SECRET", raising=False)
    monkeypatch.delenv("GOALOS_WOO_URL", raising=False)
    monkeypatch.delenv("GOALOS_WOO_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("GOALOS_WOO_CONSUMER_SECRET", raising=False)
    connector = WooCommerceConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED


def test_woocommerce_health_capability() -> None:
    connector = _connector(_opener())
    result = connector.execute("woocommerce.health", {}, permissions={Permission.READ_WEBSITE})
    assert result["configured"] is True
    assert result["integration"] == "woocommerce"
