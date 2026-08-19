"""Pydantic schemas for WooCommerce webhook ingestion.

Request schemas validate the raw payloads WooCommerce and the abandoned-cart
bridge deliver; response schemas structure the API acknowledgement after
ingestion.  None of these schemas are stored directly — the service layer
normalises them into database models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# Generic webhook ingestion response
# --------------------------------------------------------------------------- #

class WebhookIngestResult(BaseModel):
    """Structured result after ingesting one WooCommerce / cart webhook."""

    accepted: bool
    status: str
    source: str
    event_type: str
    event_id: str | None = None
    record_id: str | None = None
    reason: str | None = None


# --------------------------------------------------------------------------- #
# WooCommerce order webhook request (raw WooCommerce payload)
# --------------------------------------------------------------------------- #

class WooOrderLineItem(BaseModel):
    """One line item inside a WooCommerce order payload."""

    id: int = 0
    name: str = ""
    product_id: int = 0
    variation_id: int = 0
    quantity: int = 0
    subtotal: str = "0"
    total: str = "0"
    subtotal_tax: str = "0"
    total_tax: str = "0"
    sku: str = ""
    meta_data: list[dict[str, Any]] = Field(default_factory=list)


class WooOrderWebhookPayload(BaseModel):
    """WooCommerce order webhook payload (order.created / order.updated / etc.)."""

    id: int
    number: str = ""
    order_key: str = ""
    status: str = "pending"
    currency: str = "INR"
    total: str = "0"
    subtotal: str = "0"
    discount_total: str = "0"
    shipping_total: str = "0"
    cart_tax: str = "0"
    total_tax: str = "0"
    prices_include_tax: str = "no"

    customer_id: int = 0
    customer_email: str = ""
    customer_first_name: str = ""
    customer_last_name: str = ""

    billing: dict[str, Any] = Field(default_factory=dict)
    shipping: dict[str, Any] = Field(default_factory=dict)

    payment_method: str = ""
    payment_method_title: str = ""
    transaction_id: str = ""

    line_items: list[WooOrderLineItem] = Field(default_factory=list)
    coupon_lines: list[dict[str, Any]] = Field(default_factory=list)
    shipping_lines: list[dict[str, Any]] = Field(default_factory=list)

    date_created: str = ""
    date_modified: str = ""


# --------------------------------------------------------------------------- #
# Abandoned cart webhook request (bridge payload)
# --------------------------------------------------------------------------- #

class AbandonedCartItemPayload(BaseModel):
    """One product line in the abandoned-cart bridge payload."""

    product_id: int = 0
    variation_id: int = 0
    sku: str = ""
    product_name: str = ""
    quantity: int = 0
    unit_price: float = 0.0
    line_total: float = 0.0


class AbandonedCartWebhookPayload(BaseModel):
    """Abandoned-cart event payload delivered by the WordPress bridge.

    Fields match what Abandoned Cart Lite makes available through the
    WordPress bridge: cart ID, customer details (may be empty for
    anonymous visitors), currency, total, and the cart items.
    """

    event_id: str = ""
    event_type: str = "cart.abandoned"
    source: str = "abandoned_cart_lite"
    cart_id: str
    customer_id: int = 0
    customer_name: str = ""
    customer_email: str = ""
    customer_phone: str = ""
    currency: str = "INR"
    cart_total: float = 0.0
    abandoned_at: str = ""
    cart_items: list[AbandonedCartItemPayload] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Order / Cart list responses
# --------------------------------------------------------------------------- #

class WooCommerceOrderItemResponse(BaseModel):
    """API representation of one order line item."""

    id: UUID
    product_id: int
    variation_id: int
    sku: str
    name: str
    quantity: int
    subtotal: float
    total: float

    model_config = {"from_attributes": True}


class WooCommerceOrderResponse(BaseModel):
    """API representation of a persisted WooCommerce order."""

    id: UUID
    woo_order_id: int
    order_number: str | None = None
    status: str
    currency: str
    total: float
    subtotal: float
    discount_total: float
    shipping_total: float
    tax_total: float
    customer_id: int
    customer_email: str
    customer_first_name: str
    customer_last_name: str
    billing_phone: str
    payment_method_title: str
    woo_date_created: datetime | None = None
    source_event_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WooCommerceAbandonedCartItemResponse(BaseModel):
    """API representation of one abandoned cart line item."""

    id: UUID
    product_id: int
    variation_id: int
    sku: str
    product_name: str
    quantity: int
    unit_price: float
    line_total: float

    model_config = {"from_attributes": True}


class WooCommerceAbandonedCartResponse(BaseModel):
    """API representation of a persisted abandoned cart."""

    id: UUID
    cart_id: str
    customer_id: int
    customer_email: str
    customer_first_name: str
    customer_last_name: str
    currency: str
    cart_total: float
    item_count: int
    status: str
    abandoned_at: datetime | None = None
    recovered_woo_order_id: int | None = None
    recovery_revenue: float | None = None
    recovered_at: datetime | None = None
    source_event_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
