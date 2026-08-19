"""Persistence repository for WooCommerce order records."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models.woocommerce_order import WooCommerceOrder, WooCommerceOrderItem


class WooCommerceOrderRepository:
    """Database access for WooCommerce order records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_woo_id(self, woo_order_id: int) -> WooCommerceOrder | None:
        """Return an order by its WooCommerce order ID."""
        statement = select(WooCommerceOrder).where(
            WooCommerceOrder.woo_order_id == woo_order_id
        )
        return self.db.scalars(statement).one_or_none()

    def get_by_source_event_id(self, source_event_id: str) -> WooCommerceOrder | None:
        """Return a previously ingested order with the same source event id."""
        statement = select(WooCommerceOrder).where(
            WooCommerceOrder.source_event_id == source_event_id
        )
        return self.db.scalars(statement).one_or_none()

    def get(self, order_id: uuid.UUID) -> WooCommerceOrder | None:
        return self.db.scalars(
            select(WooCommerceOrder).where(WooCommerceOrder.id == order_id)
        ).one_or_none()

    def create(self, values: dict[str, Any], items: list[dict[str, Any]] | None = None) -> WooCommerceOrder:
        """Create a new order with optional line items."""
        order = WooCommerceOrder(**values)
        self.db.add(order)
        self.db.flush()  # get the order.id for FK
        if items:
            for item_data in items:
                item = WooCommerceOrderItem(order_id=order.id, **item_data)
                self.db.add(item)
        self.db.commit()
        self.db.expire(order)
        # Re-query to load selectin relationships (line_items)
        loaded = self.get_by_woo_id(order.woo_order_id)
        return loaded or order

    def update(self, order: WooCommerceOrder, updates: dict[str, Any]) -> WooCommerceOrder:
        for field, value in updates.items():
            setattr(order, field, value)
        self.db.commit()
        self.db.expire(order)
        loaded = self.get_by_woo_id(order.woo_order_id)
        return loaded or order

    def list_orders(
        self,
        *,
        limit: int = 100,
        status: str | None = None,
    ) -> Sequence[WooCommerceOrder]:
        statement = select(WooCommerceOrder).order_by(WooCommerceOrder.created_at.desc())
        if status:
            statement = statement.where(WooCommerceOrder.status == status)
        return self.db.scalars(statement.limit(min(max(limit, 1), 500))).all()

    def count(self) -> int:
        return int(self.db.scalar(select(func.count()).select_from(WooCommerceOrder)) or 0)

    def find_by_customer_email(self, email: str) -> WooCommerceOrder | None:
        """Return the most recent order for a given customer email."""
        if not email:
            return None
        statement = (
            select(WooCommerceOrder)
            .where(WooCommerceOrder.customer_email == email)
            .order_by(WooCommerceOrder.created_at.desc())
            .limit(1)
        )
        return self.db.scalars(statement).one_or_none()
