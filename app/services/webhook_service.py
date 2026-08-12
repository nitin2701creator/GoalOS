"""Webhook/event ingestion for GoalOS.

``WebhookService`` receives external webhook events (currently Twenty CRM
record-created/updated/deleted), validates their signature, protects against
replay, persists every event as a durable record, and exposes a dispatch
seam so events can later be routed into the existing workflow/scheduler/
execution architecture.

Security contract (consistent with the existing constant-time comparison
used by the ``/v1`` surface):

- Signature validation follows Twenty's convention: HMAC-SHA256 of the
  string ``{timestamp}:{payload}`` using ``GOALOS_TWENTY_WEBHOOK_SECRET``,
  compared with :func:`hmac.compare_digest` (constant time).
- Replay protection: the signed ``X-Twenty-Webhook-Timestamp`` must be
  within a tolerance window, and the deterministic event key (event type +
  record id + event timestamp) is de-duplicated in the database.
- Nothing is acknowledged without a persisted record: accepted events are
  stored with ``status=received`` before the HTTP 2xx response; rejected
  events are stored with ``status=rejected`` for audit.
- The secret is never logged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from app.db.models.event import EventRecord, EventStatus
from app.repositories.event_repository import EventRepository
from app.schemas.event import WebhookIngestResponse

logger = logging.getLogger(__name__)

#: Header names used by Twenty webhooks (current + legacy fallback).
_SIGNATURE_HEADERS = ("x-twenty-webhook-signature", "x-twenty-signature")
_TIMESTAMP_HEADER = "x-twenty-webhook-timestamp"

#: Replay tolerance: events signed more than this far in the past (or
#: future) are rejected.
TIMESTAMP_TOLERANCE = timedelta(minutes=5)


def _header(headers: Mapping[str, str], *names: str) -> str | None:
    """Return the first present header value (case-insensitive)."""
    lowered = {key.casefold(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value and value.strip():
            return value.strip()
    return None


def derive_event_id(event: str, data: dict[str, Any], timestamp: str) -> str:
    """Deterministic replay key: event type + record id + event timestamp."""
    record_id = data.get("id") or data.get("recordId") or ""
    return f"{event}:{record_id}:{timestamp}"


class WebhookService:
    """Validate, persist, and dispatch webhook events."""

    def __init__(
        self,
        repository: EventRepository,
        *,
        secret: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.secret = secret or os.getenv("GOALOS_TWENTY_WEBHOOK_SECRET") or ""
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._handlers: list[Callable[[EventRecord], None]] = []

    @property
    def is_configured(self) -> bool:
        """Return whether a webhook secret is configured."""
        return bool(self.secret)

    def register_handler(self, handler: Callable[[EventRecord], None]) -> None:
        """Register an event dispatcher (future workflow/scheduler routing)."""
        self._handlers.append(handler)

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------
    def ingest_twenty(
        self,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> WebhookIngestResponse:
        """Validate and persist one Twenty webhook delivery.

        Raises:
            WebhookNotConfiguredError: When no secret is configured.
            WebhookRejectedError: When the signature/timestamp is invalid or
                the payload cannot be parsed. Rejected deliveries are still
                persisted (status=rejected) for audit when parseable.
        """
        if not self.secret:
            raise WebhookNotConfiguredError(
                "GOALOS_TWENTY_WEBHOOK_SECRET is not configured; refusing webhooks"
            )

        signature = _header(headers, *_SIGNATURE_HEADERS)
        timestamp = _header(headers, _TIMESTAMP_HEADER)
        if not signature or not timestamp:
            self._persist_rejected(
                raw_body, "missing signature or timestamp headers", headers=headers
            )
            raise WebhookRejectedError(
                "missing X-Twenty-Webhook-Signature or X-Twenty-Webhook-Timestamp header"
            )

        if not self._signature_valid(raw_body, timestamp, signature):
            self._persist_rejected(
                raw_body, "invalid webhook signature", headers=headers
            )
            raise WebhookRejectedError("invalid webhook signature")

        if not self._timestamp_within_tolerance(timestamp):
            self._persist_rejected(
                raw_body, f"webhook timestamp outside tolerance ({timestamp})", headers=headers
            )
            raise WebhookRejectedError(f"webhook timestamp is outside the tolerance window: {timestamp}")

        payload = self._parse_payload(raw_body)
        event_name = str(payload.get("event") or payload.get("name") or "unknown.event")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        payload_timestamp = str(
            payload.get("timestamp") or data.get("updatedAt") or data.get("createdAt") or timestamp
        )
        event_id = derive_event_id(event_name, data, payload_timestamp)

        existing = self.repository.get_by_event_id(event_id, source="twenty")
        if existing is not None:
            return WebhookIngestResponse(
                accepted=False,
                status=EventStatus.DUPLICATE.value,
                event_id=event_id,
                event_type=event_name,
                reason="event was already ingested (duplicate delivery)",
            )

        object_type = event_name.rsplit(".", 1)[0] if "." in event_name else None
        record_id = data.get("id") or data.get("recordId")
        event = self.repository.create(
            {
                "source": "twenty",
                "event_type": event_name,
                "event_id": event_id,
                "object_type": object_type,
                "object_id": str(record_id) if record_id is not None else None,
                "payload": payload,
                "signature_valid": True,
                "status": EventStatus.RECEIVED,
            }
        )
        self._dispatch(event)
        return WebhookIngestResponse(
            accepted=True,
            status=EventStatus.RECEIVED.value,
            event_id=event_id,
            event_type=event_name,
            reason="event persisted and acknowledged",
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _signature_valid(self, raw_body: bytes, timestamp: str, signature: str) -> bool:
        """Verify the Twenty HMAC-SHA256 signature (constant time).

        The signature covers ``{timestamp}:{payload}``. Twenty signs the
        JSON-stringified request body; we try the raw body first and fall
        back to a compact JSON re-serialization of the parsed body for
        deliverers that normalize whitespace.
        """
        candidates = [raw_body.decode("utf-8", errors="replace")]
        try:
            parsed = json.loads(raw_body.decode("utf-8", errors="replace"))
            candidates.append(
                json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)
            )
        except (json.JSONDecodeError, TypeError):
            pass
        for payload_text in dict.fromkeys(candidates):
            expected = hmac.new(
                self.secret.encode(),
                f"{timestamp}:{payload_text}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if hmac.compare_digest(expected, signature.casefold()):
                return True
        return False

    def _timestamp_within_tolerance(self, timestamp: str) -> bool:
        """Reject signed timestamps outside the replay tolerance window."""
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        now = self._now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return abs(now - parsed) <= TIMESTAMP_TOLERANCE

    def _parse_payload(self, raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, TypeError) as exc:
            raise WebhookRejectedError(f"payload is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise WebhookRejectedError("payload must be a JSON object")
        return payload

    def _persist_rejected(
        self,
        raw_body: bytes,
        reason: str,
        *,
        headers: Mapping[str, str],
    ) -> None:
        """Persist a rejected delivery for audit when the payload is parseable."""
        try:
            payload = json.loads(raw_body.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, TypeError):
            payload = {"raw": raw_body.decode("utf-8", errors="replace")[:2000]}
        if not isinstance(payload, dict):
            payload = {"raw": str(payload)}
        event_name = str(payload.get("event") or "unknown.event")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        record_id = data.get("id") or data.get("recordId")
        timestamp = str(
            payload.get("timestamp")
            or data.get("updatedAt")
            or data.get("createdAt")
            or _header(headers, _TIMESTAMP_HEADER)
            or ""
        )
        try:
            self.repository.create(
                {
                    "source": "twenty",
                    "event_type": event_name,
                    "event_id": derive_event_id(event_name, data, timestamp),
                    "object_type": event_name.rsplit(".", 1)[0] if "." in event_name else None,
                    "object_id": str(record_id) if record_id is not None else None,
                    "payload": payload,
                    "signature_valid": False,
                    "status": EventStatus.REJECTED,
                    "error": reason,
                }
            )
        except Exception:  # audit persistence must never break the response
            logger.warning("could not persist rejected webhook event", exc_info=True)

    def _dispatch(self, event: EventRecord) -> None:
        """Notify registered handlers (workflow/scheduler routing seam)."""
        for handler in self._handlers:
            try:
                handler(event)
            except Exception:  # dispatch must not break acknowledgment
                logger.warning("webhook event handler failed", exc_info=True)


class WebhookError(Exception):
    """Base error for webhook ingestion failures."""


class WebhookNotConfiguredError(WebhookError):
    """Raised when no webhook secret is configured."""


class WebhookRejectedError(WebhookError):
    """Raised when a webhook delivery fails validation."""
