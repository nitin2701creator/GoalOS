"""Comprehensive tests for WooCommerce order and abandoned-cart webhook ingestion.

Tests cover:
1. Valid abandoned-cart event
2. Invalid abandoned-cart authentication
3. Missing cart ID
4. Anonymous cart (no customer info)
5. Cart with multiple items
6. Valid WooCommerce order.created event
7. Valid WooCommerce order.updated event
8. Order status change
9. Invalid WooCommerce signature
10. Duplicate webhook delivery (idempotency)
11. Same order updated multiple times
12. Abandoned cart recovered by order
13. Recovery revenue calculation
14. Missing optional customer information
15. Malformed payload
16. Database failure / transaction rollback
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.event import EventRecord, EventStatus
from app.db.models.woocommerce_cart import AbandonedCartStatus, WooCommerceAbandonedCart
from app.db.models.woocommerce_order import WooCommerceOrder
from app.repositories.event_repository import EventRepository
from app.repositories.woocommerce_cart_repository import WooCommerceCartRepository
from app.repositories.woocommerce_order_repository import WooCommerceOrderRepository
from app.schemas.woocommerce import (
    AbandonedCartWebhookPayload,
    WebhookIngestResult,
    WooOrderWebhookPayload,
)
from app.services.woocommerce_webhook_service import (
    WebhookAuthError,
    WebhookPayloadError,
    WooCommerceWebhookService,
    derive_cart_event_id,
    derive_woo_event_id,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WOO_SECRET = "test_woo_webhook_secret_abc123"
CART_SECRET = "test_abandoned_cart_secret_xyz789"


@pytest.fixture()
def engine():
    """Create an in-memory SQLite engine with all WooCommerce tables."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    """Provide a transactional session that rolls back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


def _make_service(db: Session) -> WooCommerceWebhookService:
    return WooCommerceWebhookService(db, woo_secret=WOO_SECRET, cart_secret=CART_SECRET)


def _sign_woo(body: bytes, secret: str) -> str:
    """Compute the HMAC-SHA256 WooCommerce signature for a body."""
    sig_bytes = hmac_mod.new(secret.encode(), body, hashlib.sha256).digest()
    return base64.b64encode(sig_bytes).decode()


def _make_woo_headers(
    body: bytes,
    *,
    topic: str = "order.created",
    delivery_id: str = "12345",
    source: str = "https://organigram.example.com",
    webhook_id: str = "100",
    include_signature: bool = True,
) -> dict[str, str]:
    """Build realistic WooCommerce webhook headers."""
    headers = {
        "X-WC-Webhook-Topic": topic,
        "X-WC-Webhook-Delivery-ID": delivery_id,
        "X-WC-Webhook-Source": source,
        "X-WC-Webhook-ID": webhook_id,
    }
    if include_signature:
        headers["X-WC-Webhook-Signature"] = _sign_woo(body, WOO_SECRET)
    return headers


def _make_woo_order_payload(
    *,
    order_id: int = 5001,
    status: str = "pending",
    total: str = "1250.00",
    customer_email: str = "test@example.com",
    customer_first_name: str = "Test",
    customer_last_name: str = "User",
) -> dict:
    """Build a realistic WooCommerce order webhook payload."""
    return {
        "id": order_id,
        "number": str(order_id),
        "order_key": f"wc_order_{order_id}",
        "status": status,
        "currency": "INR",
        "total": total,
        "subtotal": "1100.00",
        "discount_total": "50.00",
        "shipping_total": "100.00",
        "cart_tax": "50.00",
        "total_tax": "50.00",
        "prices_include_tax": "no",
        "customer_id": 1,
        "customer_email": customer_email,
        "customer_first_name": customer_first_name,
        "customer_last_name": customer_last_name,
        "billing": {
            "first_name": customer_first_name,
            "last_name": customer_last_name,
            "email": customer_email,
            "phone": "+919876543210",
            "address_1": "123 Test Street",
            "address_2": "",
            "city": "Mumbai",
            "state": "MH",
            "postcode": "400001",
            "country": "IN",
        },
        "shipping": {
            "first_name": customer_first_name,
            "last_name": customer_last_name,
            "address_1": "123 Test Street",
            "address_2": "",
            "city": "Mumbai",
            "state": "MH",
            "postcode": "400001",
            "country": "IN",
        },
        "payment_method": "upi",
        "payment_method_title": "UPI",
        "transaction_id": "TXN123456",
        "line_items": [
            {
                "id": 1,
                "name": "Test Product",
                "product_id": 101,
                "variation_id": 0,
                "quantity": 2,
                "subtotal": "550.00",
                "total": "600.00",
                "subtotal_tax": "25.00",
                "total_tax": "25.00",
                "sku": "TP-001",
                "meta_data": [],
            }
        ],
        "coupon_lines": [],
        "shipping_lines": [],
        "date_created": "2026-08-19T10:30:00",
        "date_modified": "2026-08-19T10:35:00",
    }


def _make_cart_payload(
    *,
    cart_id: str = "acl_12345",
    customer_email: str = "cart@example.com",
    customer_name: str = "Cart User",
    total: float = 750.00,
    items: list | None = None,
) -> dict:
    """Build a realistic abandoned-cart bridge payload."""
    if items is None:
        items = [
            {
                "product_id": 201,
                "variation_id": 0,
                "sku": "CP-001",
                "product_name": "Cart Product",
                "quantity": 1,
                "unit_price": 750.00,
                "line_total": 750.00,
            }
        ]
    return {
        "event_id": "",
        "event_type": "cart.abandoned",
        "source": "abandoned_cart_lite",
        "cart_id": cart_id,
        "customer_id": 2,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": "+919876543211",
        "currency": "INR",
        "cart_total": total,
        "abandoned_at": "2026-08-19T10:25:00Z",
        "cart_items": items,
    }


# ---------------------------------------------------------------------------
# Helper classes for testing
# ---------------------------------------------------------------------------


class _FakeHeaders(dict):
    """Dict subclass that supports case-insensitive header lookup like real request headers."""

    def get(self, key: str, default=None):
        key_lower = key.casefold()
        for k, v in self.items():
            if k.casefold() == key_lower:
                return v
        return default

    def __getitem__(self, key: str):
        key_lower = key.casefold()
        for k, v in self.items():
            if k.casefold() == key_lower:
                return v
        raise KeyError(key)


def _fake_headers(d: dict[str, str]) -> _FakeHeaders:
    return _FakeHeaders(d)


# ============================================================================
# Test 1: Valid abandoned-cart event
# ============================================================================

class TestValidAbandonedCart:
    def test_accepted_cart_event(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        result = svc.ingest_abandoned_cart(body, headers)

        assert isinstance(result, WebhookIngestResult)
        assert result.accepted is True
        assert result.status == "received"
        assert result.source == "abandoned_cart"
        assert result.event_type == "cart.abandoned"
        assert result.record_id == "acl_12345"

        # Verify DB record
        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart is not None
        assert cart.status == AbandonedCartStatus.ABANDONED.value
        assert cart.cart_total == 750.00
        assert cart.customer_email == "cart@example.com"
        assert cart.item_count == 1

    def test_cart_items_persisted(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        svc.ingest_abandoned_cart(body, headers)

        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart is not None
        assert len(cart.items) == 1
        assert cart.items[0].product_id == 201
        assert cart.items[0].product_name == "Cart Product"
        assert cart.items[0].quantity == 1
        assert cart.items[0].unit_price == 750.00


# ============================================================================
# Test 2: Invalid abandoned-cart authentication
# ============================================================================

class TestInvalidCartAuth:
    def test_missing_auth_header(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({})

        with pytest.raises(WebhookAuthError, match="missing or malformed"):
            svc.ingest_abandoned_cart(body, headers)

    def test_wrong_token(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": "Bearer wrong_secret"})

        with pytest.raises(WebhookAuthError, match="invalid abandoned-cart"):
            svc.ingest_abandoned_cart(body, headers)

    def test_no_secret_configured(self, db):
        svc = WooCommerceWebhookService(db, woo_secret=WOO_SECRET, cart_secret="")
        payload = _make_cart_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer anything"})

        with pytest.raises(WebhookAuthError, match="not configured"):
            svc.ingest_abandoned_cart(body, headers)


# ============================================================================
# Test 3: Missing cart ID
# ============================================================================

class TestMissingCartId:
    def test_missing_cart_id_rejected(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload()
        del payload["cart_id"]
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        with pytest.raises(WebhookPayloadError, match="missing 'cart_id'"):
            svc.ingest_abandoned_cart(body, headers)


# ============================================================================
# Test 4: Anonymous cart (no customer info)
# ============================================================================

class TestAnonymousCart:
    def test_anonymous_cart_accepted(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload(
            customer_email="",
            customer_name="",
        )
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        result = svc.ingest_abandoned_cart(body, headers)

        assert result.accepted is True
        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart is not None
        assert cart.customer_email == ""
        assert cart.customer_first_name == ""
        assert cart.customer_last_name == ""


# ============================================================================
# Test 5: Cart with multiple items
# ============================================================================

class TestMultiItemCart:
    def test_multi_item_cart(self, db):
        svc = _make_service(db)
        items = [
            {
                "product_id": 201,
                "variation_id": 0,
                "sku": "CP-001",
                "product_name": "Product A",
                "quantity": 2,
                "unit_price": 250.00,
                "line_total": 500.00,
            },
            {
                "product_id": 202,
                "variation_id": 10,
                "sku": "CP-002-V10",
                "product_name": "Product B (Red)",
                "quantity": 1,
                "unit_price": 350.00,
                "line_total": 350.00,
            },
        ]
        payload = _make_cart_payload(total=850.00, items=items)
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        result = svc.ingest_abandoned_cart(body, headers)

        assert result.accepted is True
        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart is not None
        assert cart.item_count == 2
        assert cart.cart_total == 850.00
        assert len(cart.items) == 2
        assert cart.items[0].product_name == "Product A"
        assert cart.items[1].variation_id == 10


# ============================================================================
# Test 6: Valid WooCommerce order.created event
# ============================================================================

class TestOrderCreated:
    def test_order_created_accepted(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body)

        result = svc.ingest_woo_order(body, _fake_headers(headers))

        assert result.accepted is True
        assert result.status == "received"
        assert result.source == "woocommerce"
        assert result.event_type == "order.created"
        assert result.record_id == "5001"

    def test_order_persisted_in_db(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body)

        svc.ingest_woo_order(body, _fake_headers(headers))

        order_repo = WooCommerceOrderRepository(db)
        order = order_repo.get_by_woo_id(5001)
        assert order is not None
        assert order.status == "pending"
        assert order.total == 1250.00
        assert order.currency == "INR"
        assert order.customer_email == "test@example.com"
        assert order.billing_phone == "+919876543210"
        assert order.payment_method == "upi"

    def test_line_items_persisted(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body)

        svc.ingest_woo_order(body, _fake_headers(headers))

        order_repo = WooCommerceOrderRepository(db)
        order = order_repo.get_by_woo_id(5001)
        assert len(order.line_items) == 1
        assert order.line_items[0].product_id == 101
        assert order.line_items[0].name == "Test Product"
        assert order.line_items[0].quantity == 2


# ============================================================================
# Test 7: Valid WooCommerce order.updated event
# ============================================================================

class TestOrderUpdated:
    def test_order_updated_accepted(self, db):
        svc = _make_service(db)
        # First create the order
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body, topic="order.created")
        svc.ingest_woo_order(body, _fake_headers(headers))

        # Now update the order
        payload["status"] = "processing"
        payload["total"] = "1500.00"
        body2 = json.dumps(payload).encode()
        headers2 = _make_woo_headers(body2, topic="order.updated", delivery_id="12346")
        result = svc.ingest_woo_order(body2, _fake_headers(headers2))

        assert result.accepted is True
        assert result.event_type == "order.updated"

        order_repo = WooCommerceOrderRepository(db)
        order = order_repo.get_by_woo_id(5001)
        assert order.status == "processing"
        assert order.total == 1500.00


# ============================================================================
# Test 8: Order status change
# ============================================================================

class TestOrderStatusChange:
    def test_pending_to_completed(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload(status="pending")
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body, topic="order.created")
        svc.ingest_woo_order(body, _fake_headers(headers))

        payload["status"] = "completed"
        body2 = json.dumps(payload).encode()
        headers2 = _make_woo_headers(body2, topic="order.updated", delivery_id="20001")
        result = svc.ingest_woo_order(body2, _fake_headers(headers2))

        assert result.accepted is True
        order_repo = WooCommerceOrderRepository(db)
        order = order_repo.get_by_woo_id(5001)
        assert order.status == "completed"

    def test_all_statuses(self, db):
        svc = _make_service(db)
        for i, status in enumerate(["pending", "processing", "on-hold", "completed", "cancelled", "refunded", "failed"]):
            payload = _make_woo_order_payload(order_id=6000 + i, status=status)
            body = json.dumps(payload).encode()
            headers = _make_woo_headers(body, topic="order.created", delivery_id=str(30000 + i))
            result = svc.ingest_woo_order(body, _fake_headers(headers))
            assert result.accepted is True

            order_repo = WooCommerceOrderRepository(db)
            order = order_repo.get_by_woo_id(6000 + i)
            assert order.status == status


# ============================================================================
# Test 9: Invalid WooCommerce signature
# ============================================================================

class TestInvalidSignature:
    def test_missing_signature(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({
            "X-WC-Webhook-Topic": "order.created",
            "X-WC-Webhook-Delivery-ID": "999",
        })

        with pytest.raises(WebhookAuthError, match="missing X-WC-Webhook-Signature"):
            svc.ingest_woo_order(body, headers)

    def test_wrong_signature(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({
            "X-WC-Webhook-Topic": "order.created",
            "X-WC-Webhook-Delivery-ID": "999",
            "X-WC-Webhook-Signature": base64.b64encode(b"wrong_signature").decode(),
        })

        with pytest.raises(WebhookAuthError, match="invalid WooCommerce webhook"):
            svc.ingest_woo_order(body, headers)

    def test_no_secret_configured(self, db):
        svc = WooCommerceWebhookService(db, woo_secret="", cart_secret=CART_SECRET)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({
            "X-WC-Webhook-Topic": "order.created",
            "X-WC-Webhook-Delivery-ID": "999",
            "X-WC-Webhook-Signature": "anything",
        })

        with pytest.raises(WebhookAuthError, match="not configured"):
            svc.ingest_woo_order(body, headers)


# ============================================================================
# Test 10: Duplicate webhook delivery (idempotency)
# ============================================================================

class TestDuplicateDelivery:
    def test_duplicate_order_delivery(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body, delivery_id="55555")

        result1 = svc.ingest_woo_order(body, _fake_headers(headers))
        assert result1.accepted is True

        # Same delivery ID → duplicate
        result2 = svc.ingest_woo_order(body, _fake_headers(headers))
        assert result2.accepted is False
        assert result2.status == "duplicate"

    def test_duplicate_cart_delivery(self, db):
        svc = _make_service(db)
        payload = _make_cart_payload()
        body = json.dumps(payload).encode()
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        result1 = svc.ingest_abandoned_cart(body, headers)
        assert result1.accepted is True

        # Same cart_id + email + abandoned_at → duplicate
        result2 = svc.ingest_abandoned_cart(body, headers)
        assert result2.accepted is False
        assert result2.status == "duplicate"


# ============================================================================
# Test 11: Same order updated multiple times
# ============================================================================

class TestMultipleOrderUpdates:
    def test_sequential_updates(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload(order_id=7000, status="pending")

        statuses = ["pending", "processing", "on-hold", "processing", "completed"]
        for i, status in enumerate(statuses):
            payload["status"] = status
            body = json.dumps(payload).encode()
            headers = _make_woo_headers(body, topic="order.updated", delivery_id=str(40000 + i))
            result = svc.ingest_woo_order(body, _fake_headers(headers))
            assert result.accepted is True

        order_repo = WooCommerceOrderRepository(db)
        order = order_repo.get_by_woo_id(7000)
        assert order.status == "completed"

        # Only one order record exists
        from sqlalchemy import select
        orders = db.scalars(select(WooCommerceOrder).where(WooCommerceOrder.woo_order_id == 7000)).all()
        assert len(orders) == 1


# ============================================================================
# Test 12: Abandoned cart recovered by order
# ============================================================================

class TestCartRecovery:
    def test_order_recovers_cart(self, db):
        svc = _make_service(db)

        # First: ingest an abandoned cart
        cart_payload = _make_cart_payload(
            customer_email="recovery@example.com",
        )
        cart_body = json.dumps(cart_payload).encode()
        cart_headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})
        svc.ingest_abandoned_cart(cart_body, cart_headers)

        # Verify cart is abandoned
        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart.status == AbandonedCartStatus.ABANDONED.value

        # Second: ingest a completed order with the same email
        order_payload = _make_woo_order_payload(
            order_id=8000,
            status="completed",
            customer_email="recovery@example.com",
            total="750.00",
        )
        order_body = json.dumps(order_payload).encode()
        order_headers = _make_woo_headers(order_body, topic="order.created", delivery_id="50001")
        svc.ingest_woo_order(order_body, _fake_headers(order_headers))

        # Verify cart is now recovered
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart.status == AbandonedCartStatus.RECOVERED.value
        assert cart.recovery_woo_order_id == 8000
        assert cart.recovery_revenue == 750.00
        assert cart.recovered_at is not None

    def test_processing_order_also_recovers(self, db):
        svc = _make_service(db)

        cart_payload = _make_cart_payload(customer_email="proc@example.com")
        svc.ingest_abandoned_cart(
            json.dumps(cart_payload).encode(),
            _fake_headers({"Authorization": f"Bearer {CART_SECRET}"}),
        )

        order_payload = _make_woo_order_payload(
            order_id=8001, status="processing",
            customer_email="proc@example.com", total="500.00",
        )
        svc.ingest_woo_order(
            json.dumps(order_payload).encode(),
            _fake_headers(_make_woo_headers(json.dumps(order_payload).encode(), delivery_id="50002")),
        )

        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart.status == AbandonedCartStatus.RECOVERED.value


# ============================================================================
# Test 13: Recovery revenue calculation
# ============================================================================

class TestRecoveryRevenue:
    def test_revenue_recorded(self, db):
        svc = _make_service(db)

        cart_payload = _make_cart_payload(customer_email="rev@example.com", total=2500.00)
        svc.ingest_abandoned_cart(
            json.dumps(cart_payload).encode(),
            _fake_headers({"Authorization": f"Bearer {CART_SECRET}"}),
        )

        order_payload = _make_woo_order_payload(
            order_id=9000, status="completed",
            customer_email="rev@example.com", total="2500.00",
        )
        svc.ingest_woo_order(
            json.dumps(order_payload).encode(),
            _fake_headers(_make_woo_headers(json.dumps(order_payload).encode(), delivery_id="60001")),
        )

        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart.recovery_revenue == 2500.00

    def test_recovery_idempotent(self, db):
        """Delivering the same order twice should not double-count recovery."""
        svc = _make_service(db)

        cart_payload = _make_cart_payload(customer_email="idem@example.com")
        svc.ingest_abandoned_cart(
            json.dumps(cart_payload).encode(),
            _fake_headers({"Authorization": f"Bearer {CART_SECRET}"}),
        )

        order_payload = _make_woo_order_payload(
            order_id=9001, status="completed",
            customer_email="idem@example.com", total="1000.00",
        )
        body = json.dumps(order_payload).encode()

        svc.ingest_woo_order(body, _fake_headers(_make_woo_headers(body, delivery_id="60002")))
        svc.ingest_woo_order(body, _fake_headers(_make_woo_headers(body, delivery_id="60002")))

        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart.status == AbandonedCartStatus.RECOVERED.value
        assert cart.recovery_revenue == 1000.00


# ============================================================================
# Test 14: Missing optional customer information
# ============================================================================

class TestMissingCustomerInfo:
    def test_order_with_empty_customer(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload(
            customer_email="",
            customer_first_name="",
            customer_last_name="",
        )
        payload["billing"] = {}
        payload["shipping"] = {}
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body, delivery_id="70001")

        result = svc.ingest_woo_order(body, _fake_headers(headers))
        assert result.accepted is True

        order_repo = WooCommerceOrderRepository(db)
        order = order_repo.get_by_woo_id(5001)
        assert order.customer_email == ""
        assert order.billing_phone == ""

    def test_order_no_recovery_without_email(self, db):
        """A completed order without email should not trigger recovery."""
        svc = _make_service(db)

        # Ingest a cart with an email
        cart_payload = _make_cart_payload(customer_email="norec@example.com")
        svc.ingest_abandoned_cart(
            json.dumps(cart_payload).encode(),
            _fake_headers({"Authorization": f"Bearer {CART_SECRET}"}),
        )

        # Ingest a completed order WITHOUT a matching email
        order_payload = _make_woo_order_payload(
            order_id=9002, status="completed",
            customer_email="someone-else@example.com", total="500.00",
        )
        svc.ingest_woo_order(
            json.dumps(order_payload).encode(),
            _fake_headers(_make_woo_headers(json.dumps(order_payload).encode(), delivery_id="70002")),
        )

        cart_repo = WooCommerceCartRepository(db)
        cart = cart_repo.get_by_cart_id("acl_12345")
        assert cart.status == AbandonedCartStatus.ABANDONED.value


# ============================================================================
# Test 15: Malformed payload
# ============================================================================

class TestMalformedPayload:
    def test_invalid_json(self, db):
        svc = _make_service(db)
        body = b"not json at all"
        headers = _make_woo_headers(body, delivery_id="80001")

        with pytest.raises(WebhookPayloadError, match="not valid JSON"):
            svc.ingest_woo_order(body, _fake_headers(headers))

    def test_json_array_not_object(self, db):
        svc = _make_service(db)
        body = json.dumps([1, 2, 3]).encode()
        headers = _make_woo_headers(body, delivery_id="80002")

        with pytest.raises(WebhookPayloadError, match="must be a JSON object"):
            svc.ingest_woo_order(body, _fake_headers(headers))

    def test_missing_order_id(self, db):
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        del payload["id"]
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body, delivery_id="80003")

        with pytest.raises(WebhookPayloadError, match="missing integer 'id'"):
            svc.ingest_woo_order(body, _fake_headers(headers))

    def test_cart_invalid_json(self, db):
        svc = _make_service(db)
        body = b"{{invalid json"
        headers = _fake_headers({"Authorization": f"Bearer {CART_SECRET}"})

        with pytest.raises(WebhookPayloadError, match="not valid JSON"):
            svc.ingest_abandoned_cart(body, headers)


# ============================================================================
# Test 16: Database failure / transaction rollback
# ============================================================================

class TestDatabaseFailure:
    def test_order_repo_failure_rolls_back(self, db):
        """When the order repo create fails, the event record should not persist either."""
        svc = _make_service(db)
        payload = _make_woo_order_payload()
        body = json.dumps(payload).encode()
        headers = _make_woo_headers(body, delivery_id="90001")

        with patch.object(
            WooCommerceOrderRepository, "create", side_effect=Exception("DB write error")
        ):
            with pytest.raises(Exception, match="DB write error"):
                svc.ingest_woo_order(body, _fake_headers(headers))


# ============================================================================
# Helper function tests
# ============================================================================

class TestHelperFunctions:
    def test_derive_woo_event_id(self):
        eid = derive_woo_event_id("order.created", 1234, "5678")
        assert eid == "wc:order.created:1234:5678"

    def test_derive_cart_event_id_deterministic(self):
        eid1 = derive_cart_event_id("cart1", "a@b.com", "2026-01-01")
        eid2 = derive_cart_event_id("cart1", "a@b.com", "2026-01-01")
        assert eid1 == eid2
        assert eid1.startswith("cart:cart1:")

    def test_derive_cart_event_id_different_inputs(self):
        eid1 = derive_cart_event_id("cart1", "a@b.com", "2026-01-01")
        eid2 = derive_cart_event_id("cart1", "c@d.com", "2026-01-01")
        assert eid1 != eid2
