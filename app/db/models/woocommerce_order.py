"""WooCommerce order and order-line-item persistence models.

Captures the structured business data GoalOS receives from WooCommerce order
webhooks (order.created / order.updated / order.deleted) so the business
services layer can reason over real revenue, status transitions, and line-item
detail without hitting the WooCommerce API.

Idempotency is enforced via ``source_event_id`` (the WooCommerce webhook
delivery ID): the unique constraint guarantees the same delivery cannot
create duplicate order records.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrderStatus(str, Enum):
    """Known WooCommerce order statuses mapped to GoalOS."""

    PENDING = "pending"
    PROCESSING = "processing"
    ON_HOLD = "on-hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    FAILED = "failed"
    TRASHED = "trashed"


class WooCommerceOrder(Base):
    """A WooCommerce order ingested through a native order webhook."""

    __tablename__ = "woocommerce_orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # -- WooCommerce identifiers ------------------------------------------------
    woo_order_id: Mapped[int] = mapped_column(
        Integer, unique=True, index=True, nullable=False
    )
    order_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")

    # -- Money ------------------------------------------------------------------
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    discount_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    shipping_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cart_tax: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # -- Customer ---------------------------------------------------------------
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    customer_first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    customer_last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    # -- Billing ----------------------------------------------------------------
    billing_first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    billing_last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    billing_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    billing_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    billing_address_1: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    billing_address_2: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    billing_city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    billing_state: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    billing_postcode: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    billing_country: Mapped[str] = mapped_column(String(10), nullable=False, default="")

    # -- Shipping ---------------------------------------------------------------
    shipping_first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    shipping_last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    shipping_address_1: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    shipping_address_2: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    shipping_city: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    shipping_state: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    shipping_postcode: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    shipping_country: Mapped[str] = mapped_column(String(10), nullable=False, default="")

    # -- Payment ----------------------------------------------------------------
    payment_method: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    payment_method_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    transaction_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # -- WooCommerce timestamps --------------------------------------------------
    woo_date_created: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    woo_date_modified: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -- Coupons ----------------------------------------------------------------
    coupon_lines: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)

    # -- Shipping lines ---------------------------------------------------------
    shipping_lines: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)

    # -- Source / idempotency ---------------------------------------------------
    source_event_id: Mapped[str] = mapped_column(
        String(200), unique=True, index=True, nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="woocommerce")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # -- Timestamps -------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # -- Relationships ----------------------------------------------------------
    line_items: Mapped[list[WooCommerceOrderItem]] = relationship(
        "WooCommerceOrderItem",
        back_populates="order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("woo_order_id", name="uq_woocommerce_order_woo_id"),
    )


class WooCommerceOrderItem(Base):
    """A single line item within a WooCommerce order."""

    __tablename__ = "woocommerce_order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("woocommerce_orders.id"), nullable=False, index=True
    )
    woo_item_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- Product ----------------------------------------------------------------
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    variation_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    # -- Quantities & money -----------------------------------------------------
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subtotal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    subtotal_tax: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_tax: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # -- Meta -------------------------------------------------------------------
    meta_data: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)

    # -- Timestamps -------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # -- Relationships ----------------------------------------------------------
    order: Mapped[WooCommerceOrder] = relationship(
        "WooCommerceOrder", back_populates="line_items"
    )
