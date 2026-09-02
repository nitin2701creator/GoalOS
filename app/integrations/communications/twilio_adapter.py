"""Twilio communication adapter for GoalOS.

Uses the Twilio REST API v2010 (HTTP Basic Auth) over stdlib
HTTP client — no Twilio SDK dependency required. Falls back to
NOT_CONFIGURED when credentials are absent.

Supports:
- Outbound voice calls (domestic + international, E.164 normalized)
- Outbound SMS (domestic + international, E.164 normalized)
- Webhook status callback parsing
- Structured error normalization
"""

from __future__ import annotations

import logging
import os
import urllib.parse
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

_TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"

# Twilio error codes that map to specific call statuses
_TWILIO_BUSY_CODES = {21218, 21214}
_TWILIO_NO_ANSWER_CODES = {21215}


def twilio_config_from_env() -> CommunicationConfig:
    """Build a Twilio config from environment variables."""
    return CommunicationConfig(
        provider="twilio",
        account_id=os.getenv("TWILIO_ACCOUNT_SID", "").strip(),
        auth_token=os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        from_number=os.getenv("TWILIO_FROM_NUMBER", "").strip(),
    )


class TwilioAdapter(BaseCommunicationAdapter):
    """Twilio REST API adapter for voice calls and SMS.

    Uses stdlib urllib with Basic Auth — zero third-party SDK dependencies.
    Supports retry on transient failures (5xx, network errors).
    """

    name = "twilio"

    def __init__(self, config: CommunicationConfig | None = None) -> None:
        super().__init__(config or twilio_config_from_env())

    def make_voice_call(self, request: VoiceCallRequest) -> VoiceCallResponse:
        if not self.is_configured:
            return VoiceCallResponse(
                provider="twilio",
                status=CallStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: Twilio credentials not set",
            )

        # Normalize numbers to E.164
        dest = normalize_e164(request.destination_number)
        if not dest:
            return VoiceCallResponse(
                provider="twilio",
                status=CallStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )
        caller = normalize_e164(request.caller_number) or self.config.from_number

        try:
            params: dict[str, str] = {
                "To": dest,
                "From": caller,
                "Twiml": f"<Response><Say>{request.message}</Say></Response>",
            }
            if request.callback_url:
                params["StatusCallback"] = request.callback_url
                params["StatusCallbackEvent"] = "initiated ringing answered completed"
            if request.max_duration_seconds:
                params["Timeout"] = str(min(request.max_duration_seconds, 120))

            body = urllib.parse.urlencode(params).encode()
            response_data = self._api_call(
                "POST",
                f"/Accounts/{self.config.account_id}/Calls.json",
                body,
            )

            # Check for API error in response
            if "code" in response_data:
                error_code = str(response_data.get("code", ""))
                error_msg = response_data.get("message", "Unknown error")
                status = self._map_error_to_status(response_data.get("code", 0))
                return VoiceCallResponse(
                    provider="twilio",
                    status=status,
                    error=f"PROVIDER_ERROR [{error_code}]: {error_msg}",
                    provider_metadata={
                        "code": error_code,
                        "more_info": response_data.get("more_info", ""),
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
                provider="twilio",
                call_id=response_data.get("sid"),
                status=status_map.get(
                    response_data.get("status", ""), CallStatus.QUEUED
                ),
                cost=response_data.get("price"),
                duration_seconds=self._parse_duration(response_data.get("duration")),
                provider_metadata={
                    "sid": response_data.get("sid"),
                    "status": response_data.get("status"),
                    "price_unit": response_data.get("price_unit"),
                    "direction": response_data.get("direction"),
                    "to": response_data.get("to"),
                    "from": response_data.get("from"),
                },
            )
        except Exception as exc:
            logger.warning("Twilio voice call failed: %s", exc)
            return VoiceCallResponse(
                provider="twilio",
                status=CallStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def send_sms(self, request: SmsRequest) -> SmsResponse:
        if not self.is_configured:
            return SmsResponse(
                provider="twilio",
                status=CommunicationStatus.NO_PROVIDER,
                error="INTEGRATION_NOT_CONFIGURED: Twilio credentials not set",
            )

        # Normalize numbers to E.164
        dest = normalize_e164(request.destination_number)
        if not dest:
            return SmsResponse(
                provider="twilio",
                status=CommunicationStatus.FAILED,
                error=f"INVALID_DESTINATION: Cannot normalize '{request.destination_number}' to E.164",
            )
        sender = normalize_e164(request.sender_number) or self.config.from_number

        try:
            params: dict[str, str] = {
                "To": dest,
                "From": sender,
                "Body": request.message,
            }
            if request.callback_url:
                params["StatusCallback"] = request.callback_url

            body = urllib.parse.urlencode(params).encode()
            response_data = self._api_call(
                "POST",
                f"/Accounts/{self.config.account_id}/Messages.json",
                body,
            )

            # Check for API error in response
            if "code" in response_data:
                error_code = str(response_data.get("code", ""))
                error_msg = response_data.get("message", "Unknown error")
                return SmsResponse(
                    provider="twilio",
                    status=CommunicationStatus.FAILED,
                    error=f"PROVIDER_ERROR [{error_code}]: {error_msg}",
                    provider_metadata={
                        "code": error_code,
                        "more_info": response_data.get("more_info", ""),
                    },
                )

            status_map = {
                "queued": CommunicationStatus.QUEUED,
                "sending": CommunicationStatus.SENT,
                "sent": CommunicationStatus.SENT,
                "delivered": CommunicationStatus.DELIVERED,
                "failed": CommunicationStatus.FAILED,
                "undelivered": CommunicationStatus.FAILED,
            }
            return SmsResponse(
                provider="twilio",
                message_id=response_data.get("sid"),
                status=status_map.get(
                    response_data.get("status", ""), CommunicationStatus.QUEUED
                ),
                cost=response_data.get("price"),
                provider_metadata={
                    "sid": response_data.get("sid"),
                    "status": response_data.get("status"),
                    "price_unit": response_data.get("price_unit"),
                    "num_segments": response_data.get("num_segments"),
                    "to": response_data.get("to"),
                    "from": response_data.get("from"),
                },
            )
        except Exception as exc:
            logger.warning("Twilio SMS failed: %s", exc)
            return SmsResponse(
                provider="twilio",
                status=CommunicationStatus.FAILED,
                error=f"PROVIDER_EXCEPTION: {exc}",
            )

    def parse_webhook(self, payload: dict) -> StatusEvent | None:
        """Parse a Twilio status callback webhook into a StatusEvent."""
        event_type_str = payload.get("Event", payload.get("StatusCallbackEvent", ""))
        call_sid = payload.get("CallSid", payload.get("MessageSid", ""))

        if not call_sid:
            return None

        # Determine if this is a call or SMS event
        is_call = "CallSid" in payload
        raw_status = payload.get("CallStatus", payload.get("MessageStatus", ""))

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
        }

        event_type = event_type_map.get(raw_status)
        if event_type is None:
            return None

        return StatusEvent(
            event_type=event_type,
            provider="twilio",
            provider_id=call_sid,
            status=raw_status,
            destination_number=payload.get("To", ""),
            source_number=payload.get("From", ""),
            duration_seconds=self._parse_duration(payload.get("CallDuration")),
            error_code=payload.get("ErrorCode"),
            error_message=payload.get("ErrorMessage"),
            metadata={
                "event_type": event_type_str,
                "api_version": payload.get("ApiVersion"),
            },
        )

    def _map_error_to_status(self, code: int) -> CallStatus:
        """Map a Twilio error code to a CallStatus."""
        if code in _TWILIO_BUSY_CODES:
            return CallStatus.BUSY
        if code in _TWILIO_NO_ANSWER_CODES:
            return CallStatus.NO_ANSWER
        return CallStatus.FAILED

    def _parse_duration(self, value: str | None) -> int | None:
        """Parse a duration string to int seconds."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _api_call(
        self, method: str, path: str, body: bytes | None = None,
        retries: int = 2,
    ) -> dict:
        """Make an authenticated Twilio API call using stdlib with retry."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        url = f"{_TWILIO_API_BASE}{path}"
        credentials = base64.b64encode(
            f"{self.config.account_id}:{self.config.auth_token}".encode()
        ).decode()

        last_error: Exception | None = None
        for attempt in range(1 + retries):
            request = Request(
                url,
                data=body,
                method=method,
                headers={
                    "Authorization": f"Basic {credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    data = response.read()
                    return json.loads(data.decode())
            except HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")
                logger.error(
                    "Twilio API %s %s returned %s (attempt %d/%d): %s",
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
                        f"Twilio API error {exc.code}: {error_body[:200]}"
                    ) from exc
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise

        # Should not reach here, but safety net
        raise ConnectionError(f"Twilio API failed after {1 + retries} attempts: {last_error}")
