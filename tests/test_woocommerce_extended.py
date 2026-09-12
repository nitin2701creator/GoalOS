"""Tests for the extended WooCommerce connector.

Covers the full product/order/customer/category/sales/variation/inventory
capability surface, write-permission gates, stable error mapping (auth
failure, rate limiting), the ``WOOCOMMERCE_*`` env aliases, store-URL
normalization, and the live connection test. Never touches a real store.
"""

from __future__ import annotations

import json
import socket

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectionStatus, ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient
from app.integrations.woocommerce import (
    WooCommerceConnector,
    normalize_store_url,
    store_connection_candidates,
)
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


# ---------------------------------------------------------------------------
# Store-URL normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("http://www.organigram.in", "http://www.organigram.in"),
    ("http://www.organigram.in/", "http://www.organigram.in"),
    ("WWW.Organigram.IN", "https://www.organigram.in"),
    ("organigram.in", "https://organigram.in"),
    ("  https://shop.example.com  ", "https://shop.example.com"),
    ("https://shop.example.com/shop", "https://shop.example.com"),
    ("http://localhost:8080", "http://localhost:8080"),
])
def test_normalize_store_url_variants(raw: str, expected: str) -> None:
    assert normalize_store_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "not a url://", "ftp://example.com"])
def test_normalize_store_url_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_store_url(raw)


def test_normalize_store_url_rejects_embedded_credentials() -> None:
    with pytest.raises(ValueError, match="credentials"):
        normalize_store_url("https://user:pass@example.com")


def test_store_connection_candidates_primary_preserves_path() -> None:
    candidates = store_connection_candidates("http://localhost:8080/shop")
    assert candidates[0] == "http://localhost:8080/shop"


def test_store_connection_candidates_www_and_scheme_fallbacks() -> None:
    candidates = store_connection_candidates("http://www.organigram.in")
    assert candidates == [
        "http://www.organigram.in",
        "http://organigram.in",
        "https://www.organigram.in",
        "https://organigram.in",
    ]


def test_store_connection_candidates_no_https_duplicates() -> None:
    assert store_connection_candidates("https://shop.example.com") == [
        "https://shop.example.com"
    ]


# ---------------------------------------------------------------------------
# Live connection test
# ---------------------------------------------------------------------------

SYSTEM_STATUS = {
    "environment": {
        "woocommerce_version": "9.1.0",
        "wp_version": "6.7",
        "site_url": "http://www.organigram.in",
    }
}


def _raise_opener(error):
    def opener(request, timeout=None):
        raise error

    return opener


def _raw_opener(body: bytes, *, status: int = 200, content_type: str = "text/html; charset=utf-8"):
    def opener(request, timeout=None):
        url = str(getattr(request, "full_url", request))
        return FakeResponse(body, url, status=status, content_type=content_type)

    return opener


def test_connection_test_missing_config_is_invalid_config() -> None:
    connector = WooCommerceConnector(client=HttpClient())
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.INVALID_CONFIG
    assert "missing configuration" in (result.message or "").lower()


def test_connection_test_invalid_url_override_is_invalid_config() -> None:
    connector = _connector(_opener())
    result = connector.connection_test(url="ftp://example.com")
    assert result.success is False
    assert result.status is ConnectionStatus.INVALID_CONFIG


def test_connection_test_success_reports_connected() -> None:
    opener = _opener({("GET", "/system_status"): SYSTEM_STATUS})
    connector = _connector(opener, base_url="http://www.organigram.in")
    result = connector.connection_test()
    assert result.success is True
    assert result.status is ConnectionStatus.CONNECTED
    assert result.details["woocommerce_version"] == "9.1.0"
    assert result.details["store_url"] == "http://www.organigram.in"
    assert ("GET", "http://www.organigram.in/wp-json/wc/v3/system_status") in opener.calls


def test_connection_test_auth_failure_is_distinct() -> None:
    opener = _opener(default_status=401, default_payload={"code": "woocommerce_rest_authentication_error"})
    connector = _connector(opener)
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.AUTH_FAILED
    assert "credentials" in (result.message or "").lower()


def test_connection_test_403_is_distinct() -> None:
    opener = _opener(default_status=403, default_payload={"code": "forbidden"})
    connector = _connector(opener)
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.AUTH_FAILED


def test_connection_test_dns_failure_falls_back_to_apex() -> None:
    def opener(request, timeout=None):
        url = str(getattr(request, "full_url", request))
        if "www.organigram.in" in url:
            raise OSError("Name or service not known")
        return FakeResponse(
            json.dumps(SYSTEM_STATUS).encode(), url, status=200,
            content_type="application/json",
        )

    connector = WooCommerceConnector(
        client=HttpClient(opener=opener),
        base_url="http://www.organigram.in",
        consumer_key="ck",
        consumer_secret="cs",
    )
    result = connector.connection_test()
    assert result.success is True
    assert result.status is ConnectionStatus.CONNECTED
    assert result.details["store_url"] == "http://organigram.in"


def test_connection_test_all_candidates_unreachable() -> None:
    connector = WooCommerceConnector(
        client=HttpClient(opener=_raise_opener(OSError("Name or service not known"))),
        base_url="http://www.organigram.in",
        consumer_key="ck",
        consumer_secret="cs",
    )
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.UNREACHABLE


def test_connection_test_timeout_is_unreachable() -> None:
    connector = WooCommerceConnector(
        client=HttpClient(opener=_raise_opener(socket.timeout("timed out"))),
        base_url="https://shop.example.com",
        consumer_key="ck",
        consumer_secret="cs",
    )
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.UNREACHABLE


def test_connection_test_html_page_is_api_unavailable() -> None:
    connector = WooCommerceConnector(
        client=HttpClient(opener=_raw_opener(b"<html><body>WordPress</body></html>")),
        base_url="https://shop.example.com",
        consumer_key="ck",
        consumer_secret="cs",
    )
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.API_UNAVAILABLE
    assert "HTML" in (result.message or "")


def test_connection_test_malformed_json_is_api_unavailable() -> None:
    connector = WooCommerceConnector(
        client=HttpClient(opener=_raw_opener(b"this is not json", content_type="application/json")),
        base_url="https://shop.example.com",
        consumer_key="ck",
        consumer_secret="cs",
    )
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.API_UNAVAILABLE


def test_connection_test_404_is_api_unavailable() -> None:
    opener = _opener(default_status=404, default_payload={"code": "rest_no_route"})
    connector = _connector(opener)
    result = connector.connection_test()
    assert result.success is False
    assert result.status is ConnectionStatus.API_UNAVAILABLE


def test_connection_test_uses_custom_api_version() -> None:
    opener = _opener({("GET", "/system_status"): SYSTEM_STATUS})
    connector = WooCommerceConnector(
        client=HttpClient(opener=opener),
        base_url="https://shop.example.com",
        consumer_key="ck",
        consumer_secret="cs",
        api_version="wc/v2",
    )
    result = connector.connection_test()
    assert result.success is True
    assert result.details["api_version"] == "wc/v2"
    assert ("GET", "https://shop.example.com/wp-json/wc/v2/system_status") in opener.calls


def test_connection_test_capability_requires_read() -> None:
    opener = _opener({("GET", "/system_status"): SYSTEM_STATUS})
    connector = _connector(opener, base_url="https://shop.example.com")
    with pytest.raises(PermissionDeniedError, match="READ_WEBSITE"):
        connector.execute("woocommerce.connection_test", {}, permissions=set())
    result = connector.execute(
        "woocommerce.connection_test", {}, permissions={Permission.READ_WEBSITE}
    )
    assert result["success"] is True
    assert result["status"] == "connected"


def test_connection_test_capability_with_url_override() -> None:
    opener = _opener({("GET", "/system_status"): SYSTEM_STATUS})
    connector = _connector(opener, base_url="https://store-not-used.example.com")
    result = connector.execute(
        "woocommerce.connection_test",
        {"url": "http://www.organigram.in"},
        permissions={Permission.READ_WEBSITE},
    )
    assert result["success"] is True
    assert result["details"]["store_url"] == "http://www.organigram.in"


def test_connection_test_never_logs_credentials(caplog: pytest.LogCaptureFixture) -> None:
    opener = _opener({("GET", "/system_status"): SYSTEM_STATUS})
    connector = _connector(opener)
    with caplog.at_level("DEBUG"):
        connector.connection_test()
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "ck" not in combined and "cs" not in combined
