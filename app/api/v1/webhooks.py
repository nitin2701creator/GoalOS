"""Webhook ingestion API for external events.

Inbound webhook endpoints:

- ``POST /api/v1/webhooks/twenty`` — Twenty CRM record events
  (HMAC-SHA256 over ``{timestamp}:{payload}`` with
  ``GOALOS_TWENTY_WEBHOOK_SECRET``).

- ``POST /api/v1/webhooks/woocommerce/order`` — WooCommerce native order
  webhooks (HMAC-SHA256 with ``GOALOS_WOOCOMMERCE_WEBHOOK_SECRET``).
  Supports order.created, order.updated, order.deleted.

- ``POST /api/v1/webhooks/abandoned-cart`` — Abandoned-cart Lite events
  delivered by the WordPress bridge, authenticated with a bearer token
  (``GOALOS_ABANDONED_CART_WEBHOOK_SECRET``).

- ``GET /api/v1/webhooks/events`` — Lists persisted events for operations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.db.session import get_db
from app.repositories.event_repository import EventRepository
from app.schemas.event import EventRecordResponse
from app.schemas.woocommerce import (
    WebhookIngestResult,
    WooCommerceAbandonedCartResponse,
    WooCommerceOrderResponse,
)
from app.services.webhook_service import (
    WebhookNotConfiguredError,
    WebhookRejectedError,
    WebhookService,
)
from app.services.woocommerce_webhook_service import (
    WebhookAuthError,
    WebhookPayloadError,
    WooCommerceWebhookError,
    WooCommerceWebhookService,
)

router = APIRouter()


# --------------------------------------------------------------------- #
# Twenty CRM                                                             #
# --------------------------------------------------------------------- #

def _get_service(db=Depends(get_db)) -> WebhookService:
    """Compose the webhook service per request (existing conventions)."""
    return WebhookService(EventRepository(db))


@router.post(
    "/webhooks/twenty",
    response_model=EventRecordResponse,
    summary="Ingest a Twenty CRM webhook event",
    description=(
        "Validate the X-Twenty-Webhook-Signature (HMAC-SHA256 of "
        "{timestamp}:{payload} with GOALOS_TWENTY_WEBHOOK_SECRET), reject "
        "replays outside the tolerance window, persist the event, and "
        "acknowledge with 2xx only after a valid receipt."
    ),
)
async def ingest_twenty_webhook(
    request: Request,
    service: WebhookService = Depends(_get_service),
):
    raw_body = await request.body()
    try:
        result = service.ingest_twenty(raw_body, request.headers)
    except WebhookNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except WebhookRejectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    if not result.accepted:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(mode="json"),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=result.model_dump(mode="json"),
    )


# --------------------------------------------------------------------- #
# WooCommerce order webhooks                                             #
# --------------------------------------------------------------------- #

def _get_woo_service(db=Depends(get_db)) -> WooCommerceWebhookService:
    """Compose the WooCommerce webhook service per request."""
    return WooCommerceWebhookService(db)


@router.post(
    "/webhooks/woocommerce/order",
    summary="Ingest a WooCommerce order webhook event",
    description=(
        "Validate the X-WC-Webhook-Signature (HMAC-SHA256 of the raw body "
        "with GOALOS_WOOCOMMERCE_WEBHOOK_SECRET), deduplicate by delivery "
        "ID, upsert the WooCommerce order, and persist the event record. "
        "Returns HTTP 202 for accepted events, 200 for safe idempotent "
        "duplicates, 401 for invalid signatures, and 503 when the webhook "
        "secret is not configured."
    ),
)
async def ingest_woo_order_webhook(
    request: Request,
    service: WooCommerceWebhookService = Depends(_get_woo_service),
):
    raw_body = await request.body()
    try:
        result = service.ingest_woo_order(raw_body, request.headers)
    except WebhookAuthError as exc:
        msg = str(exc)
        if "not configured" in msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=msg
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=msg
        ) from exc
    except WebhookPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except WooCommerceWebhookError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    status_code = (
        status.HTTP_200_OK
        if not result.accepted
        else status.HTTP_202_ACCEPTED
    )
    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


# --------------------------------------------------------------------- #
# Abandoned-cart webhooks                                                #
# --------------------------------------------------------------------- #

@router.post(
    "/webhooks/abandoned-cart",
    summary="Ingest an abandoned-cart event from the WordPress bridge",
    description=(
        "Authenticate with a bearer token "
        "(GOALOS_ABANDONED_CART_WEBHOOK_SECRET), deduplicate by a "
        "deterministic event key (cart_id + email + timestamp), persist "
        "the abandoned cart and its items, and acknowledge with HTTP 2xx. "
        "Returns 202 for accepted events, 200 for safe idempotent "
        "duplicates, 401 for invalid auth, and 503 when the secret is "
        "not configured."
    ),
)
async def ingest_abandoned_cart_webhook(
    request: Request,
    service: WooCommerceWebhookService = Depends(_get_woo_service),
):
    raw_body = await request.body()
    try:
        result = service.ingest_abandoned_cart(raw_body, request.headers)
    except WebhookAuthError as exc:
        msg = str(exc)
        if "not configured" in msg:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=msg
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=msg
        ) from exc
    except WebhookPayloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except WooCommerceWebhookError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    status_code = (
        status.HTTP_200_OK
        if not result.accepted
        else status.HTTP_202_ACCEPTED
    )
    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


# --------------------------------------------------------------------- #
# Event listing (shared)                                                 #
# --------------------------------------------------------------------- #

@router.get(
    "/webhooks/events",
    summary="List persisted webhook events",
)
def list_webhook_events(
    service: WebhookService = Depends(_get_service),
    limit: int = 100,
):
    """Return recently persisted webhook events (newest first)."""
    events = service.repository.list(limit=min(max(limit, 1), 500))
    return {
        "total": len(events),
        "events": [
            EventRecordResponse.model_validate(event).model_dump(mode="json")
            for event in events
        ],
    }


# --------------------------------------------------------------------- #
# WooCommerce data listing endpoints                                     #
# --------------------------------------------------------------------- #

@router.get(
    "/webhooks/woocommerce/debug",
    summary="WooCommerce webhook diagnostic (no secrets exposed)",
)
def woo_webhook_debug(
    service: WooCommerceWebhookService = Depends(_get_woo_service),
):
    """Return diagnostic info about the loaded webhook configuration.

    Shows whether secrets are loaded and their lengths — never the
    actual values.  Use this to verify the VPS env is correct.
    """
    import os

    info = service.get_secret_info()
    # Show which env var was actually loaded (name only, not value)
    info["env_source"] = (
        "GOALOS_WOOCOMMERCE_WEBHOOK_SECRET"
        if os.getenv("GOALOS_WOOCOMMERCE_WEBHOOK_SECRET", "").strip()
        else "WOOCOMMERCE_WEBHOOK_SECRET"
        if os.getenv("WOOCOMMERCE_WEBHOOK_SECRET", "").strip()
        else "NONE"
    )
    return info


@router.get(
    "/webhooks/woocommerce/orders",
    summary="List ingested WooCommerce orders",
)
def list_woo_orders(
    service: WooCommerceWebhookService = Depends(_get_woo_service),
    limit: int = 50,
    status_filter: str | None = None,
):
    """Return recently ingested WooCommerce orders (newest first)."""
    from sqlalchemy import select
    from app.db.models.woocommerce_order import WooCommerceOrder

    statement = select(WooCommerceOrder).order_by(WooCommerceOrder.created_at.desc())
    if status_filter:
        statement = statement.where(WooCommerceOrder.status == status_filter)
    orders = service.db.scalars(statement.limit(min(max(limit, 1), 500))).all()
    return {
        "total": len(orders),
        "orders": [
            WooCommerceOrderResponse.model_validate(o).model_dump(mode="json")
            for o in orders
        ],
    }


@router.get(
    "/webhooks/abandoned-carts",
    summary="List ingested abandoned carts",
)
def list_abandoned_carts(
    service: WooCommerceWebhookService = Depends(_get_woo_service),
    limit: int = 50,
    status_filter: str | None = None,
):
    """Return recently ingested abandoned carts (newest first)."""
    carts = service.cart_repo.list_carts(
        limit=min(max(limit, 1), 500),
        status=status_filter,
    )
    return {
        "total": len(carts),
        "carts": [
            WooCommerceAbandonedCartResponse.model_validate(c).model_dump(mode="json")
            for c in carts
        ],
    }
