"""WooCommerce abandoned cart persistence models.

Captures abandoned-cart events delivered by the WordPress bridge
(Abandoned Cart Lite plugin → custom bridge → GoalOS webhook endpoint)
so GoalOS can track cart abandonment, link recovered orders, and
measure revenue recovery — all without polling the WooCommerce API.

Idempotency is enforced via ``source_event_id`` (a deterministic hash of
cart_id + customer_email + abandoned_at): the unique constraint prevents
the same abandoned-cart event from creating duplicate records.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AbandonedCartStatus(str, Enum):
    """Lifecycle states of an abandoned cart."""

    ACTIVE = "active"
    ABANDONED = "abandoned"
    RECOVERED = "recovered"


class WooCommerceAbandonedCart(Base):
    """An abandoned WooCommerce cart ingested through the WordPress bridge."""

    __tablename__ = "woocommerce_abandoned_carts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # -- External identifiers ----------------------------------------------------
    cart_id: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)

    # -- Customer ---------------------------------------------------------------
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    customer_email: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    customer_first_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    customer_last_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    customer_phone: Mapped[str] = mapped_column(String(40), nullable=False, default="")

    # -- Cart summary -----------------------------------------------------------
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR")
    cart_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # -- Lifecycle ---------------------------------------------------------------
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AbandonedCartStatus.ABANDONED.value
    )
    abandoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -- Recovery ----------------------------------------------------------------
    recovered_order_id: Mapped[uuid.UUID | None] = mapped_column(String(36), nullable=True)
    recovery_woo_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recovery_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # -- Source / idempotency ---------------------------------------------------
    source_event_id: Mapped[str] = mapped_column(
        String(200), unique=True, index=True, nullable=False
    )
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # -- Timestamps -------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # -- Relationships ----------------------------------------------------------
    items: Mapped[list[WooCommerceAbandonedCartItem]] = relationship(
        "WooCommerceAbandonedCartItem",
        back_populates="cart",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class WooCommerceAbandonedCartItem(Base):
    """A single product line within an abandoned cart."""

    __tablename__ = "woocommerce_abandoned_cart_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    cart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("woocommerce_abandoned_carts.id"), nullable=False, index=True
    )

    # -- Product ----------------------------------------------------------------
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    variation_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sku: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    product_name: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    # -- Quantities & money -----------------------------------------------------
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    line_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # -- Timestamps -------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # -- Relationships ----------------------------------------------------------
    cart: Mapped[WooCommerceAbandonedCart] = relationship(
        "WooCommerceAbandonedCart", back_populates="items"
    )
