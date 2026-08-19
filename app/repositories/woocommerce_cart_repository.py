"""Persistence repository for WooCommerce abandoned cart records."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models.woocommerce_cart import (
    AbandonedCartStatus,
    WooCommerceAbandonedCart,
    WooCommerceAbandonedCartItem,
)


class WooCommerceCartRepository:
    """Database access for abandoned cart records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_cart_id(self, cart_id: str) -> WooCommerceAbandonedCart | None:
        """Return a cart by its external Abandoned Cart Lite cart ID."""
        statement = select(WooCommerceAbandonedCart).where(
            WooCommerceAbandonedCart.cart_id == cart_id
        )
        return self.db.scalars(statement).one_or_none()

    def get_by_source_event_id(self, source_event_id: str) -> WooCommerceAbandonedCart | None:
        """Return a previously ingested cart with the same source event id."""
        statement = select(WooCommerceAbandonedCart).where(
            WooCommerceAbandonedCart.source_event_id == source_event_id
        )
        return self.db.scalars(statement).one_or_none()

    def get(self, cart_pk_id: uuid.UUID) -> WooCommerceAbandonedCart | None:
        return self.db.scalars(
            select(WooCommerceAbandonedCart).where(WooCommerceAbandonedCart.id == cart_pk_id)
        ).one_or_none()

    def create(
        self,
        values: dict[str, Any],
        items: list[dict[str, Any]] | None = None,
    ) -> WooCommerceAbandonedCart:
        """Create a new abandoned cart with optional items."""
        cart = WooCommerceAbandonedCart(**values)
        self.db.add(cart)
        self.db.flush()
        if items:
            for item_data in items:
                item = WooCommerceAbandonedCartItem(cart_id=cart.id, **item_data)
                self.db.add(item)
        self.db.commit()
        self.db.expire(cart)
        # Re-query to load selectin relationships (items)
        loaded = self.get_by_cart_id(cart.cart_id)
        return loaded or cart

    def update(self, cart: WooCommerceAbandonedCart, updates: dict[str, Any]) -> WooCommerceAbandonedCart:
        for field, value in updates.items():
            setattr(cart, field, value)
        self.db.commit()
        self.db.expire(cart)
        loaded = self.get_by_cart_id(cart.cart_id)
        return loaded or cart

    def list_carts(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
    ) -> Sequence[WooCommerceAbandonedCart]:
        statement = select(WooCommerceAbandonedCart).order_by(
            WooCommerceAbandonedCart.created_at.desc()
        )
        if status:
            statement = statement.where(WooCommerceAbandonedCart.status == status)
        return self.db.scalars(statement.limit(min(max(limit, 1), 500))).all()

    def count(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(WooCommerceAbandonedCart)) or 0)

    def find_unrecovered_by_email(
        self, customer_email: str
    ) -> WooCommerceAbandonedCart | None:
        """Return the most recent non-recovered abandoned cart for a customer email.

        Used by the recovery linkage logic when an order arrives to check
        if the order corresponds to a previously abandoned cart.
        """
        if not customer_email:
            return None
        statement = (
            select(WooCommerceAbandonedCart)
            .where(
                WooCommerceAbandonedCart.customer_email == customer_email,
                WooCommerceAbandonedCart.status != AbandonedCartStatus.RECOVERED.value,
            )
            .order_by(WooCommerceAbandonedCart.abandoned_at.desc())
            .limit(1)
        )
        return self.db.scalars(statement).one_or_none()
