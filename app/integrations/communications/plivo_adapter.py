"""Plivo communication adapter for GoalOS.

Uses the Plivo REST API v1 over stdlib HTTP — no Plivo SDK dependency.
Falls back to NOT_CONFIGURED when credentials are absent.

Supports:
- Outbound voice calls (domestic + international, E.164 normalized)
- Outbound SMS (domestic + international, E.164 normalized)
- Webhook status callback parsing
- Structured error normalization
"""

from __future__ import annotations

import logging
import os
import base64
import json

from app.integrations.communications.base import (
    BaseCommunicationAdapter,
    CommunicationConfig,
)
from app.integrations.communications.models import (
    CallStatus,
    CommunicationStatus,
    EventType,
    SmsRequest,
    SmsResponse,
    StatusEvent,
    VoiceCallRequest,
    VoiceCallResponse,
    normalize_e164,
)

logger = logging.getLogger(__name__)

_PLIVO_API_BASE = "https://api.plivo.com/v1"


def plivo_config_from_env() -> CommunicationConfig:
    """Build a Plivo config from environment variables."""
    return CommunicationConfig(
        provider="plivo",
        account_id=os.getenv("PLIVO_AUTH_ID", "").strip(),
        auth_token=os.getenv("PLIVO_AUTH_TOKEN", "").strip(),
        from_number=os.getenv("PLIVO_FROM_NUMBER", "").strip(),
    )


class PlivoAdapter(BaseCommunicationAdapter):
    """Plivo REST API adapter for voice calls and SMS.

    Uses stdlib urllib with Basic Auth — zero third-party SDK dependencies.
    Supports retry on transient failures (5xx, network errors).
    """

    name = "plivo"

    def __init__(self, config: CommunicationConfig | None = None) -> None:
        super().__init__(config or plivo_config_from_env())

    def make_voice_call(self, request: VoiceCallRequest) -> VoiceCallResponse:
        if not self.is_configured:
            return VoiceCallResponse(
                provider="plivo",
                status=CallStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: Plivo credentials not set",
            )

        # Normalize numbers to E.164
        dest = normalize_e164(request.destination_number)
        if not dest:
            return VoiceCallResponse(
                provider="plivo",
                status=CallStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )
        caller = normalize_e164(request.caller_number) or self.config.from_number

        try:
            payload: dict = {
                "src": caller,
                "dst": dest,
                "text": request.message,
                "type": "text",
            }
            if request.callback_url:
                payload["url"] = request.callback_url
            if request.max_duration_seconds:
                payload["ring_timeout"] = str(min(request.max_duration_seconds, 120))

            body = json.dumps(payload).encode()
            response_data = self._api_call(
                "POST", "/Call/", body, content_type="application/json"
            )

            # Plivo returns error in the response body
            if "error" in response_data:
                error_msg = response_data.get("error", "Unknown error")
                error_code = response_data.get("error_code", "")
                return VoiceCallResponse(
                    provider="plivo",
                    status=CallStatus.FAILED,
                    error=f"PROVIDER_ERROR [{error_code}]: {error_msg}",
                    provider_metadata={
                        "error": error_msg,
                        "error_code": error_code,
                        "request_uuid": response_data.get("request_uuid", ""),
                    },
                )

            status_map = {
                "queued": CallStatus.QUEUED,
                "initiated": CallStatus.INITIATED,
                "ringing": CallStatus.INITIATED,
                "in-progress": CallStatus.IN_PROGRESS,
                "completed": CallStatus.COMPLETED,
                "busy": CallStatus.BUSY,
                "no-answer": CallStatus.NO_ANSWER,
                "failed": CallStatus.FAILED,
                "canceled": CallStatus.FAILED,
            }
            return VoiceCallResponse(
                provider="plivo",
                call_id=response_data.get("request_uuid"),
                status=status_map.get(
                    response_data.get("status", ""), CallStatus.QUEUED
                ),
                provider_metadata={
                    "request_uuid": response_data.get("request_uuid"),
                    "status": response_data.get("status"),
                    "message": response_data.get("message"),
                    "to": response_data.get("to"),
                    "from": response_data.get("from"),
                },
            )
        except Exception as exc:
            logger.warning("Plivo voice call failed: %s", exc)
            return VoiceCallResponse(
                provider="plivo",
                status=CallStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def send_sms(self, request: SmsRequest) -> SmsResponse:
        if not self.is_configured:
            return SmsResponse(
                provider="plivo",
                status=CommunicationStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: Plivo credentials not set",
            )

        # Normalize numbers to E.164
        dest = normalize_e164(request.destination_number)
        if not dest:
            return SmsResponse(
                provider="plivo",
                status=CommunicationStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )
        sender = normalize_e164(request.sender_number) or self.config.from_number

        try:
            payload: dict = {
                "src": sender,
                "dst": dest,
                "text": request.message,
            }
            if request.callback_url:
                payload["url"] = request.callback_url

            body = json.dumps(payload).encode()
            response_data = self._api_call(
                "POST", "/Message/", body, content_type="application/json"
            )

            # Plivo returns error in the response body
            if "error" in response_data:
                error_msg = response_data.get("error", "Unknown error")
                error_code = response_data.get("error_code", "")
                return SmsResponse(
                    provider="plivo",
                    status=CommunicationStatus.FAILED,
                    error=f"PROVIDER_ERROR [{error_code}]: {error_msg}",
                    provider_metadata={
                        "error": error_msg,
                        "error_code": error_code,
                    },
                )

            status_map = {
                "queued": CommunicationStatus.QUEUED,
                "sent": CommunicationStatus.SENT,
                "delivered": CommunicationStatus.DELIVERED,
                "failed": CommunicationStatus.FAILED,
            }
            message_uuid = (
                response_data.get("message_uuid", [])
                if isinstance(response_data.get("message_uuid"), list)
                else [response_data.get("message_uuid")]
            )
            return SmsResponse(
                provider="plivo",
                message_id=message_uuid[0] if message_uuid else None,
                status=status_map.get(
                    response_data.get("status", ""), CommunicationStatus.QUEUED
                ),
                provider_metadata={
                    "message_uuid": message_uuid,
                    "status": response_data.get("status"),
                    "message": response_data.get("message"),
                },
            )
        except Exception as exc:
            logger.warning("Plivo SMS failed: %s", exc)
            return SmsResponse(
                provider="plivo",
                status=CommunicationStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def parse_webhook(self, payload: dict) -> StatusEvent | None:
        """Parse a Plivo webhook callback into a StatusEvent."""
        request_uuid = payload.get("RequestUUID", payload.get("MessageUUID", ""))
        if not request_uuid:
            return None

        is_call = "CallUUID" in payload or "RequestUUID" in payload
        raw_status = payload.get("CallStatus", payload.get("MessageState", ""))

        event_type_map: dict[str, EventType] = {
            "initiated": EventType.CALL_INITIATED if is_call else EventType.SMS_QUEUED,
            "ringing": EventType.CALL_RINGING,
            "answered": EventType.CALL_ANSWERED,
            "completed": EventType.CALL_COMPLETED if is_call else EventType.SMS_DELIVERED,
            "busy": EventType.CALL_BUSY,
            "no-answer": EventType.CALL_NO_ANSWER,
            "failed": EventType.CALL_FAILED if is_call else EventType.SMS_FAILED,
            "canceled": EventType.CALL_FAILED,
            "sent": EventType.SMS_SENT,
            "delivered": EventType.SMS_DELIVERED,
            "undelivered": EventType.SMS_FAILED,
            "expired": EventType.SMS_FAILED,
        }

        event_type = event_type_map.get(raw_status)
        if event_type is None:
            return None

        # Parse duration if available
        duration = None
        if "CallDuration" in payload:
            try:
                duration = int(payload["CallDuration"])
            except (ValueError, TypeError):
                pass

        return StatusEvent(
            event_type=event_type,
            provider="plivo",
            provider_id=request_uuid,
            status=raw_status,
            destination_number=payload.get("To", payload.get("Destination", "")),
            source_number=payload.get("From", payload.get("CallerName", "")),
            duration_seconds=duration,
            error_code=payload.get("ErrorCode"),
            error_message=payload.get("ErrorMessage"),
            metadata={
                "bill_rate": payload.get("BillRate"),
                "call_uuid": payload.get("CallUUID", ""),
            },
        )

    def _api_call(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        content_type: str = "application/x-www-form-urlencoded",
        retries: int = 2,
    ) -> dict:
        """Make an authenticated Plivo API call using stdlib with retry."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        url = f"{_PLIVO_API_BASE}{path}"
        credentials = base64.b64encode(
            f"{self.config.account_id}:{self.config.auth_token}".encode()
        ).decode()

        last_error: Exception | None = None
        for attempt in range(1 + retries):
            headers: dict[str, str] = {"Authorization": f"Basic {credentials}"}
            if body:
                headers["Content-Type"] = content_type
            request = Request(url, data=body, method=method, headers=headers)
            try:
                with urlopen(request, timeout=30) as response:
                    data = response.read()
                    return json.loads(data.decode())
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                logger.error(
                    "Plivo API %s %s returned %s (attempt %d/%d): %s",
                    method, path, exc.code, attempt + 1, 1 + retries,
                    error_body[:200],
                )
                last_error = exc
                # Retry on 5xx transient errors
                if exc.code >= 500 and attempt < retries:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                # Parse error response
                try:
                    return json.loads(error_body)
                except (json.JSONDecodeError, ValueError):
                    raise ConnectionError(
                        f"Plivo API error {exc.code}: {error_body[:200]}"
                    ) from exc
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise

        raise ConnectionError(f"Plivo API failed after {1 + retries} attempts: {last_error}")
