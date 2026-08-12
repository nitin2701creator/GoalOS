"""Webhook ingestion API for external events (currently Twenty CRM).

``POST /api/v1/webhooks/twenty`` receives Twenty record-created/updated/
deleted deliveries, validates the HMAC-SHA256 signature against
``GOALOS_TWENTY_WEBHOOK_SECRET``, protects against replay, persists every
event as a durable record, and acknowledges with HTTP 2xx only after a valid
receipt. Invalid signatures and out-of-tolerance timestamps are rejected
(and persisted as rejected events for audit). The endpoint is authenticated
by the webhook signature itself — no bearer key is required from Twenty.

``GET /api/v1/webhooks/events`` lists persisted events for operations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.db.session import get_db
from app.repositories.event_repository import EventRepository
from app.schemas.event import EventRecordResponse
from app.services.webhook_service import (
    WebhookNotConfiguredError,
    WebhookRejectedError,
    WebhookService,
)

router = APIRouter()


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
        # Duplicate delivery: safe idempotent acknowledgment (200).
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=result.model_dump(mode="json"),
        )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=result.model_dump(mode="json"),
    )


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
