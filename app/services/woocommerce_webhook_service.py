"""WooCommerce and abandoned-cart webhook ingestion service.

Handles two inbound event streams:

1. **WooCommerce order webhooks** — verified with HMAC-SHA256
   (``X-WC-Webhook-Signature``) and deduplicated by delivery ID
   (``X-WC-Webhook-Delivery-ID``).  Supports ``order.created``,
   ``order.updated``, and ``order.deleted``.

2. **Abandoned-cart bridge events** — authenticated with a separate
   bearer token (``Authorization: Bearer <secret>``) and deduplicated
   by a deterministic event key derived from cart_id + email + timestamp.

Both streams persist every event in the existing ``EventRecord`` table
for audit, then normalise the payload into dedicated order/cart models
for business logic.

Recovery linkage: when an order arrives with a customer email that matches
an unrecovered abandoned cart, the cart is marked ``recovered`` and the
revenue is recorded.  This is idempotent — re-delivering the same order
event does not double-count recovery.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import logging
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.event import EventRecord, EventStatus
from app.db.models.woocommerce_cart import AbandonedCartStatus
from app.db.models.woocommerce_order import WooCommerceOrder
from app.repositories.event_repository import EventRepository
from app.repositories.woocommerce_cart_repository import WooCommerceCartRepository
from app.repositories.woocommerce_order_repository import WooCommerceOrderRepository
from app.schemas.woocommerce import (
    AbandonedCartWebhookPayload,
    WebhookIngestResult,
    WooOrderWebhookPayload,
)

logger = logging.getLogger(__name__)

#: WooCommerce webhook signature header
_WC_SIGNATURE_HEADER = "x-wc-webhook-signature"
_WC_DELIVERY_ID_HEADER = "x-wc-webhook-delivery-id"
_WC_TOPIC_HEADER = "x-wc-webhook-topic"
_WC_SOURCE_HEADER = "x-wc-webhook-source"
_WC_WEBHOOK_ID_HEADER = "x-wc-webhook-id"


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """Return a header value (case-insensitive) if present and non-empty."""
    for key, value in headers.items():
        if key.casefold() == name.casefold() and value and value.strip():
            return value.strip()
    return None


def derive_woo_event_id(topic: str, order_id: int, delivery_id: str) -> str:
    """Deterministic idempotency key for a WooCommerce webhook delivery."""
    return f"wc:{topic}:{order_id}:{delivery_id}"


def derive_cart_event_id(cart_id: str, email: str, abandoned_at: str) -> str:
    """Deterministic idempotency key for an abandoned-cart event."""
    raw = f"{cart_id}:{email}:{abandoned_at}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:32]
    return f"cart:{cart_id}:{digest}"


class WooCommerceWebhookService:
    """Validate, persist, normalise, and dispatch WooCommerce / cart webhooks."""

    def __init__(
        self,
        db: Session,
        *,
        woo_secret: str | None = None,
        cart_secret: str | None = None,
    ) -> None:
        self.db = db
        self.event_repo = EventRepository(db)
        self.order_repo = WooCommerceOrderRepository(db)
        self.cart_repo = WooCommerceCartRepository(db)
        self._woo_secret = (
            (woo_secret or "").strip()
            or os.getenv("GOALOS_WOOCOMMERCE_WEBHOOK_SECRET", "").strip()
            or os.getenv("WOOCOMMERCE_WEBHOOK_SECRET", "").strip()
        )
        self._cart_secret = (
            (cart_secret or "").strip()
            or os.getenv("GOALOS_ABANDONED_CART_WEBHOOK_SECRET", "").strip()
        )

    # ================================================================== #
    # WooCommerce order webhooks                                          #
    # ================================================================== #

    def ingest_woo_order(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookIngestResult:
        """Validate and persist one WooCommerce order webhook delivery.

        Raises:
            WebhookAuthError:  Signature missing / invalid or secret not configured.
            WebhookPayloadError: Body is not valid JSON or is missing id.
        """
        if not self._woo_secret:
            raise WebhookAuthError(
                "GOALOS_WOOCOMMERCE_WEBHOOK_SECRET is not configured; refusing webhooks"
            )

        # --- Signature verification ---
        signature = _header(headers, _WC_SIGNATURE_HEADER)
        if not signature:
            self._persist_event(
                "woocommerce", "order.missing_signature", None, None,
                raw_body, EventStatus.REJECTED, "missing X-WC-Webhook-Signature header",
            )
            raise WebhookAuthError("missing X-WC-Webhook-Signature header")

        if not self._verify_woo_signature(raw_body, signature):
            self._persist_event(
                "woocommerce", "order.invalid_signature", None, None,
                raw_body, EventStatus.REJECTED, "invalid WooCommerce webhook signature",
            )
            raise WebhookAuthError("invalid WooCommerce webhook signature")

        # --- Parse payload ---
        payload = self._parse_json(raw_body)

        # --- Extract event metadata ---
        delivery_id = _header(headers, _WC_DELIVERY_ID_HEADER) or ""
        topic = _header(headers, _WC_TOPIC_HEADER) or "order.created"
        source_url = _header(headers, _WC_SOURCE_HEADER) or ""
        webhook_id = _header(headers, _WC_WEBHOOK_ID_HEADER) or ""

        order_id = payload.get("id")
        if not isinstance(order_id, int):
            raise WebhookPayloadError("payload missing integer 'id' field")

        event_type = topic  # e.g. order.created
        event_id = derive_woo_event_id(topic, order_id, delivery_id)

        # --- Idempotency check ---
        existing_event = self.event_repo.get_by_event_id(event_id, source="woocommerce")
        if existing_event is not None:
            return WebhookIngestResult(
                accepted=False,
                status="duplicate",
                source="woocommerce",
                event_type=event_type,
                event_id=event_id,
                record_id=str(order_id),
                reason="event was already ingested (duplicate delivery)",
            )

        # --- Persist raw event record ---
        event_record = self._persist_event(
            "woocommerce",
            event_type,
            event_id,
            str(order_id),
            raw_body,
            EventStatus.RECEIVED,
            None,
        )

        # --- Normalise and upsert order ---
        woo_status = str(payload.get("status", "pending"))
        order = self._upsert_order(order_id, event_type, event_id, payload)

        # --- Recovery linkage ---
        if woo_status in ("completed", "processing"):
            self._attempt_recovery(order)

        return WebhookIngestResult(
            accepted=True,
            status="received",
            source="woocommerce",
            event_type=event_type,
            event_id=event_id,
            record_id=str(order_id),
            reason=f"order {woo_status} — persisted",
        )

    # ================================================================== #
    # Abandoned-cart webhooks                                             #
    # ================================================================== #

    def ingest_abandoned_cart(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookIngestResult:
        """Validate and persist one abandoned-cart event from the WP bridge.

        Raises:
            WebhookAuthError:  Bearer token missing / invalid or secret not configured.
            WebhookPayloadError: Body is not valid JSON or missing cart_id.
        """
        if not self._cart_secret:
            raise WebhookAuthError(
                "GOALOS_ABANDONED_CART_WEBHOOK_SECRET is not configured; refusing webhooks"
            )

        # --- Bearer token verification ---
        auth_header = _header(headers, "authorization") or ""
        if not auth_header.startswith("Bearer "):
            self._persist_event(
                "abandoned_cart", "cart.missing_auth", None, None,
                raw_body, EventStatus.REJECTED, "missing or malformed Authorization header",
            )
            raise WebhookAuthError("missing or malformed Authorization header")

        token = auth_header[7:].strip()
        if not hmac_mod.compare_digest(token, self._cart_secret):
            self._persist_event(
                "abandoned_cart", "cart.invalid_auth", None, None,
                raw_body, EventStatus.REJECTED, "invalid abandoned-cart webhook token",
            )
            raise WebhookAuthError("invalid abandoned-cart webhook token")

        # --- Parse payload ---
        payload = self._parse_json(raw_body)

        cart_id = payload.get("cart_id")
        if not cart_id:
            raise WebhookPayloadError("payload missing 'cart_id' field")

        # --- Deterministic event id ---
        email = payload.get("customer_email", "")
        abandoned_at = payload.get("abandoned_at", "")
        event_id = derive_cart_event_id(str(cart_id), email, abandoned_at)

        # --- Idempotency check ---
        existing_event = self.event_repo.get_by_event_id(event_id, source="abandoned_cart")
        if existing_event is not None:
            return WebhookIngestResult(
                accepted=False,
                status="duplicate",
                source="abandoned_cart",
                event_type="cart.abandoned",
                event_id=event_id,
                record_id=str(cart_id),
                reason="event was already ingested (duplicate delivery)",
            )

        # --- Persist raw event ---
        self._persist_event(
            "abandoned_cart",
            "cart.abandoned",
            event_id,
            str(cart_id),
            raw_body,
            EventStatus.RECEIVED,
            None,
        )

        # --- Normalise and upsert cart ---
        cart = self._upsert_cart(cart_id, event_id, payload)

        return WebhookIngestResult(
            accepted=True,
            status="received",
            source="abandoned_cart",
            event_type="cart.abandoned",
            event_id=event_id,
            record_id=str(cart_id),
            reason="abandoned cart persisted",
        )

    # ================================================================== #
    # WooCommerce HMAC verification                                       #
    # ================================================================== #

    def _verify_woo_signature(self, raw_body: bytes, signature: str) -> bool:
        """Verify WooCommerce HMAC-SHA256 signature.

        WooCommerce signs: base64(HMAC-SHA256(body, secret))
        """
        try:
            expected_bytes = hmac_mod.new(
                self._woo_secret.encode(),
                raw_body,
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(expected_bytes).decode()
            match = hmac_mod.compare_digest(expected, signature)
            if not match:
                logger.warning(
                    "WooCommerce webhook signature mismatch — "
                    "received sig starts=%s ends=%s (len=%d), "
                    "computed sig starts=%s ends=%s (len=%d), "
                    "secret len=%d, body len=%d",
                    signature[:4], signature[-4:], len(signature),
                    expected[:4], expected[-4:], len(expected),
                    len(self._woo_secret), len(raw_body),
                )
            return match
        except Exception:
            logger.exception("WooCommerce HMAC verification raised an exception")
            return False

    # ================================================================== #
    # Order upsert                                                        #
    # ================================================================== #

    def _upsert_order(
        self,
        woo_order_id: int,
        event_type: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> WooCommerceOrder:
        """Create or update a WooCommerce order record from webhook payload."""
        billing = payload.get("billing") or {}
        shipping = payload.get("shipping") or {}

        line_items_raw = payload.get("line_items") or []
        line_items = []
        for li in line_items_raw:
            line_items.append({
                "woo_item_id": li.get("id", 0),
                "product_id": li.get("product_id", 0),
                "variation_id": li.get("variation_id", 0),
                "sku": li.get("sku", ""),
                "name": li.get("name", ""),
                "quantity": li.get("quantity", 0),
                "subtotal": float(li.get("subtotal", "0") or "0"),
                "total": float(li.get("total", "0") or "0"),
                "subtotal_tax": float(li.get("subtotal_tax", "0") or "0"),
                "total_tax": float(li.get("total_tax", "0") or "0"),
                "meta_data": li.get("meta_data") or [],
            })

        values = {
            "woo_order_id": woo_order_id,
            "order_number": str(payload.get("number", "")),
            "status": str(payload.get("status", "pending")),
            "currency": str(payload.get("currency", "INR")),
            "total": float(payload.get("total", "0") or "0"),
            "subtotal": float(payload.get("subtotal", "0") or "0"),
            "discount_total": float(payload.get("discount_total", "0") or "0"),
            "shipping_total": float(payload.get("shipping_total", "0") or "0"),
            "cart_tax": float(payload.get("cart_tax", "0") or "0"),
            "tax_total": float(payload.get("total_tax", "0") or "0"),
            "customer_id": int(payload.get("customer_id", 0) or 0),
            "customer_email": str(payload.get("customer_email", "") or billing.get("email", "")),
            "customer_first_name": str(payload.get("customer_first_name", "") or billing.get("first_name", "")),
            "customer_last_name": str(payload.get("customer_last_name", "") or billing.get("last_name", "")),
            "billing_first_name": str(billing.get("first_name", "")),
            "billing_last_name": str(billing.get("last_name", "")),
            "billing_email": str(billing.get("email", "")),
            "billing_phone": str(billing.get("phone", "")),
            "billing_address_1": str(billing.get("address_1", "")),
            "billing_address_2": str(billing.get("address_2", "")),
            "billing_city": str(billing.get("city", "")),
            "billing_state": str(billing.get("state", "")),
            "billing_postcode": str(billing.get("postcode", "")),
            "billing_country": str(billing.get("country", "")),
            "shipping_first_name": str(shipping.get("first_name", "")),
            "shipping_last_name": str(shipping.get("last_name", "")),
            "shipping_address_1": str(shipping.get("address_1", "")),
            "shipping_address_2": str(shipping.get("address_2", "")),
            "shipping_city": str(shipping.get("city", "")),
            "shipping_state": str(shipping.get("state", "")),
            "shipping_postcode": str(shipping.get("postcode", "")),
            "shipping_country": str(shipping.get("country", "")),
            "payment_method": str(payload.get("payment_method", "")),
            "payment_method_title": str(payload.get("payment_method_title", "")),
            "transaction_id": str(payload.get("transaction_id", "")),
            "prices_include_tax": str(payload.get("prices_include_tax", "no")).casefold() == "yes",
            "coupon_lines": payload.get("coupon_lines") or [],
            "shipping_lines": payload.get("shipping_lines") or [],
            "source_event_id": event_id,
            "raw_payload": payload,
        }

        # Parse WooCommerce timestamps
        for key in ("date_created", "date_modified"):
            raw_ts = payload.get(key, "")
            if raw_ts:
                try:
                    values[f"woo_{key}"] = datetime.fromisoformat(
                        raw_ts.replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError):
                    pass

        existing = self.order_repo.get_by_woo_id(woo_order_id)
        if existing:
            # Update existing order
            order = self.order_repo.update(existing, values)
            logger.info("updated WooCommerce order %s (status=%s)", woo_order_id, values.get("status"))
            return order

        # Create new order with line items
        order = self.order_repo.create(values, items=line_items)
        logger.info("created WooCommerce order %s (status=%s)", woo_order_id, values.get("status"))
        return order

    # ================================================================== #
    # Cart upsert                                                         #
    # ================================================================== #

    def _upsert_cart(
        self,
        cart_id: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> Any:
        """Create or update an abandoned-cart record from the bridge payload."""
        items_raw = payload.get("cart_items") or []
        cart_items = []
        for ci in items_raw:
            cart_items.append({
                "product_id": ci.get("product_id", 0),
                "variation_id": ci.get("variation_id", 0),
                "sku": ci.get("sku", ""),
                "product_name": ci.get("product_name", ""),
                "quantity": ci.get("quantity", 0),
                "unit_price": float(ci.get("unit_price", 0) or 0),
                "line_total": float(ci.get("line_total", 0) or 0),
            })

        # Parse customer_name into first/last
        full_name = str(payload.get("customer_name", ""))
        parts = full_name.strip().split(None, 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        # Parse abandoned_at
        abandoned_at = None
        raw_ts = payload.get("abandoned_at", "")
        if raw_ts:
            try:
                abandoned_at = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        values = {
            "cart_id": str(cart_id),
            "customer_id": int(payload.get("customer_id", 0) or 0),
            "customer_email": str(payload.get("customer_email", "")),
            "customer_first_name": first_name,
            "customer_last_name": last_name,
            "customer_phone": str(payload.get("customer_phone", "")),
            "currency": str(payload.get("currency", "INR")),
            "cart_total": float(payload.get("cart_total", 0) or 0),
            "item_count": len(items_raw),
            "status": AbandonedCartStatus.ABANDONED.value,
            "abandoned_at": abandoned_at,
            "source_event_id": event_id,
            "raw_payload": payload,
        }

        existing = self.cart_repo.get_by_cart_id(cart_id)
        if existing:
            cart = self.cart_repo.update(existing, values)
            logger.info("updated abandoned cart %s", cart_id)
            return cart

        cart = self.cart_repo.create(values, items=cart_items)
        logger.info("created abandoned cart %s (items=%d)", cart_id, len(cart_items))
        return cart

    # ================================================================== #
    # Recovery linkage                                                    #
    # ================================================================== #

    def _attempt_recovery(self, order: WooCommerceOrder) -> None:
        """Check if this order matches an unrecovered abandoned cart.

        Matching is by customer email: if the order's customer email matches
        an unrecovered abandoned cart, the cart is marked ``recovered``.
        This is idempotent — re-delivering the same order won't double-count.
        """
        email = order.customer_email
        if not email:
            return

        cart = self.cart_repo.find_unrecovered_by_email(email)
        if cart is None:
            return

        # Already recovered (idempotency guard)
        if cart.status == AbandonedCartStatus.RECOVERED.value:
            return

        try:
            self.cart_repo.update(cart, {
                "status": AbandonedCartStatus.RECOVERED.value,
                "recovered_order_id": str(order.id),
                "recovery_woo_order_id": order.woo_order_id,
                "recovery_revenue": order.total,
                "recovered_at": datetime.now(timezone.utc),
            })
            logger.info(
                "recovered abandoned cart %s via order %s (revenue=%.2f %s)",
                cart.cart_id,
                order.woo_order_id,
                order.total,
                order.currency,
            )
        except Exception:
            logger.warning(
                "recovery linkage failed for cart %s / order %s",
                cart.cart_id,
                order.woo_order_id,
                exc_info=True,
            )

    # ================================================================== #
    # Helpers                                                             #
    # ================================================================== #

    def _parse_json(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, TypeError) as exc:
            raise WebhookPayloadError(f"payload is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise WebhookPayloadError("payload must be a JSON object")
        return payload

    def _persist_event(
        self,
        source: str,
        event_type: str,
        event_id: str | None,
        object_id: str | None,
        raw_body: bytes,
        status: EventStatus,
        error: str | None,
    ) -> EventRecord:
        """Persist a raw event record for audit."""
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="replace"))
        except Exception:
            payload = {"raw": raw_body.decode("utf-8", errors="replace")[:4000]}

        return self.event_repo.create({
            "source": source,
            "event_type": event_type,
            "event_id": event_id,
            "object_type": "order" if source == "woocommerce" else "cart",
            "object_id": object_id,
            "payload": payload,
            "signature_valid": status != EventStatus.REJECTED,
            "status": status,
            "error": error,
        })


# ====================================================================== #
# Error classes                                                           #
# ====================================================================== #

class WooCommerceWebhookError(Exception):
    """Base error for WooCommerce webhook ingestion failures."""


class WebhookAuthError(WooCommerceWebhookError):
    """Raised when webhook authentication fails."""


class WebhookPayloadError(WooCommerceWebhookError):
    """Raised when webhook payload is invalid."""
