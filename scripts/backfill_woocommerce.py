#!/usr/bin/env python3
"""Backfill historical WooCommerce orders into GoalOS and sync customers to Twenty CRM.

Uses the existing WooCommerceConnector, WooCommerceWebhookService, and
TwentyConnector — no new integrations.

Usage:
    cd /opt/GoalOS
    .venv/bin/python scripts/backfill_woocommerce.py [--dry-run] [--limit N] [--sync-twenty]

Environment variables required:
    WOOCOMMERCE_URL (or GOALOS_WOO_URL)
    WOOCOMMERCE_CONSUMER_KEY (or GOALOS_WOO_CONSUMER_KEY)
    WOOCOMMERCE_CONSUMER_SECRET (or GOALOS_WOO_CONSUMER_SECRET)
    TWENTY_BASE_URL / TWENTY_API_KEY  (only for --sync-twenty)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Allow invocation from any working directory.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.models.woocommerce_order import WooCommerceOrder  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.integrations.exceptions import (  # noqa: E402
    AuthenticationError,
    ConnectorError,
    RateLimitError,
)
from app.integrations.twenty import TwentyConnector  # noqa: E402
from app.integrations.woocommerce import WooCommerceConnector  # noqa: E402
from app.services.woocommerce_webhook_service import (  # noqa: E402
    WooCommerceWebhookService,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("backfill")


def fetch_all_orders(connector: WooCommerceConnector, max_pages: int = 100) -> list[dict[str, Any]]:
    """Fetch all orders from WooCommerce REST API with pagination."""
    all_orders: list[dict[str, Any]] = []
    page = 1
    per_page = 100  # WooCommerce max

    while page <= max_pages:
        logger.info("Fetching orders page %d (per_page=%d)...", page, per_page)
        try:
            result = connector._list("/orders", {"per_page": per_page, "page": page})
            items = result.get("items", [])
            if not items:
                logger.info("No more orders on page %d — done.", page)
                break
            all_orders.extend(items)
            logger.info("Page %d: got %d orders (total so far: %d)", page, len(items), len(all_orders))
            page += 1
            # Be polite to WooCommerce API
            time.sleep(0.5)
        except AuthenticationError as exc:
            logger.error("AUTHENTICATION_FAILED while fetching page %d: %s", page, exc)
            break
        except RateLimitError as exc:
            logger.warning("Rate limited on page %d — waiting 5s and retrying...", page)
            time.sleep(5)
            continue
        except ConnectorError as exc:
            logger.error("WooCommerce API error on page %d: %s", page, exc)
            break
        except Exception as exc:
            logger.error("Unexpected error on page %d: %s", page, exc)
            break

    return all_orders


def backfill_orders(
    db: Session,
    woo_service: WooCommerceWebhookService,
    orders: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, int]:
    """Persist orders into GoalOS database using existing upsert logic."""
    created = 0
    updated = 0
    skipped = 0
    errors = 0

    for i, order_data in enumerate(orders):
        woo_id = order_data.get("id")
        if not isinstance(woo_id, int):
            logger.warning("Order %d: missing integer id, skipping", i)
            skipped += 1
            continue

        event_id = f"backfill:order:{woo_id}"

        if dry_run:
            existing = woo_service.order_repo.get_by_woo_id(woo_id)
            if existing:
                updated += 1
            else:
                created += 1
            continue

        try:
            existing = woo_service.order_repo.get_by_woo_id(woo_id)
            woo_service._upsert_order(woo_id, "order.backfill", event_id, order_data)
            if existing:
                updated += 1
                if (updated % 50) == 0:
                    logger.info("Progress: %d created, %d updated, %d skipped", created, updated, skipped)
            else:
                created += 1
                if (created % 50) == 0:
                    logger.info("Progress: %d created, %d updated, %d skipped", created, updated, skipped)
        except Exception as exc:
            logger.error("Failed to backfill order %s: %s", woo_id, exc)
            errors += 1

    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


def sync_customers_to_twenty(
    db: Session,
    twenty: TwentyConnector,
    orders: list[dict[str, Any]],
    dry_run: bool = False,
) -> dict[str, int]:
    """Extract unique customers from orders and create/update them in Twenty."""
    created = 0
    skipped = 0
    errors = 0
    seen_emails: set[str] = set()

    # Extract unique customers from orders
    customers: list[dict[str, Any]] = []
    for order_data in orders:
        billing = order_data.get("billing") or {}
        email = billing.get("email") or order_data.get("customer_email") or ""
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)
        customers.append({
            "email": email,
            "first_name": billing.get("first_name") or order_data.get("customer_first_name") or "",
            "last_name": billing.get("last_name") or order_data.get("customer_last_name") or "",
            "phone": billing.get("phone") or "",
            "city": billing.get("city") or "",
            "country": billing.get("country") or "",
        })

    logger.info("Found %d unique customers to sync to Twenty", len(customers))

    for i, cust in enumerate(customers):
        if dry_run:
            created += 1
            continue

        try:
            # Search for existing person by email
            search_result = twenty._search("people", {"filter": {"email": {"eq": cust["email"]}}})
            existing_items = search_result.get("items", [])

            if existing_items:
                # Person exists — skip
                skipped += 1
                continue

            # Create new person
            fields = {
                "firstName": cust["first_name"],
                "lastName": cust["last_name"],
                "email": cust["email"],
            }
            if cust["phone"]:
                fields["phone"] = cust["phone"]
            if cust["city"]:
                fields["city"] = cust["city"]
            if cust["country"]:
                fields["country"] = cust["country"]

            twenty._create("people", {"fields": fields})
            created += 1

            if (created % 25) == 0:
                logger.info("Twenty sync progress: %d created, %d skipped", created, skipped)

        except Exception as exc:
            logger.error("Failed to sync customer %s to Twenty: %s", cust["email"], exc)
            errors += 1

    return {"created": created, "skipped": skipped, "errors": errors}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill WooCommerce orders into GoalOS")
    parser.add_argument("--dry-run", action="store_true", help="Count without persisting")
    parser.add_argument("--limit", type=int, default=0, help="Max pages to fetch (0 = all)")
    parser.add_argument("--sync-twenty", action="store_true", help="Also sync customers to Twenty CRM")
    args = parser.parse_args()

    # --- WooCommerce connector ---
    woo = WooCommerceConnector()
    status, msg = woo._configuration_status()
    if status.value != "Healthy":
        logger.error("WooCommerce not configured: %s", msg)
        sys.exit(1)
    logger.info("WooCommerce: %s", msg)

    # --- Fetch orders ---
    max_pages = args.limit if args.limit > 0 else 100
    logger.info("Fetching WooCommerce orders (max %d pages)...", max_pages)
    orders = fetch_all_orders(woo, max_pages=max_pages)
    logger.info("Total orders fetched: %d", len(orders))

    if not orders:
        logger.info("No orders found — nothing to backfill.")
        return

    # --- GoalOS database ---
    db = SessionLocal()
    try:
        woo_service = WooCommerceWebhookService(db)

        # --- Backfill orders ---
        logger.info("Backfilling %d orders into GoalOS...", len(orders))
        result = backfill_orders(db, woo_service, orders, dry_run=args.dry_run)
        logger.info(
            "Order backfill complete: created=%d updated=%d skipped=%d errors=%d",
            result["created"], result["updated"], result["skipped"], result["errors"],
        )

        # --- Sync to Twenty ---
        if args.sync_twenty:
            twenty = TwentyConnector()
            t_status, t_msg = twenty._configuration_status()
            if t_status.value != "Healthy":
                logger.warning("Twenty CRM not configured: %s — skipping sync", t_msg)
            else:
                logger.info("Syncing customers to Twenty CRM...")
                twenty_result = sync_customers_to_twenty(db, twenty, orders, dry_run=args.dry_run)
                logger.info(
                    "Twenty sync complete: created=%d skipped=%d errors=%d",
                    twenty_result["created"], twenty_result["skipped"], twenty_result["errors"],
                )

        # --- Summary ---
        total_orders_in_db = woo_service.order_repo.count()
        logger.info("Total WooCommerce orders in GoalOS DB: %d", total_orders_in_db)

    finally:
        db.close()


if __name__ == "__main__":
    main()
