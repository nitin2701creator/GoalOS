"""GoalOS Communication Service — provider-neutral orchestration layer.

Provides make_voice_call() and send_sms() that dispatch through the
active provider chain (primary → fallback) via the factory. Returns
structured results rather than raising exceptions. Integrates with the
action policy engine for approval enforcement.

Supports metrics tracking for capacity advisor integration.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.integrations.communications.base import BaseCommunicationAdapter
from app.integrations.communications.factory import (
    get_active_provider,
    get_provider_chain,
)
from app.integrations.communications.models import (
    CallStatus,
    CommunicationStatus,
    SmsRequest,
    SmsResponse,
    VoiceCallRequest,
    VoiceCallResponse,
    normalize_e164,
)
from app.services.action_policy import (
    ActionPolicyEngine,
    PolicyDecision,
    SPRINT1_ACTIONS,
)

logger = logging.getLogger(__name__)

#: Module-level policy engine (shared with Sprint 1 action policy).
_policy = ActionPolicyEngine()
_policy.register_many(SPRINT1_ACTIONS)


# ---------------------------------------------------------------------------
# Communication metrics (lightweight, in-memory for capacity advisor)
# ---------------------------------------------------------------------------

class _CommMetrics:
    """Track communication usage metrics for capacity advisor."""

    def __init__(self) -> None:
        self.voice_calls_attempted: int = 0
        self.voice_calls_succeeded: int = 0
        self.voice_calls_failed: int = 0
        self.sms_sent: int = 0
        self.sms_succeeded: int = 0
        self.sms_failed: int = 0
        self.fallback_used: int = 0
        self.last_error: str | None = None
        self.last_call_time: float | None = None
        self.last_sms_time: float | None = None
        self._total_call_duration: float = 0.0

    def record_voice_call(self, success: bool, duration: float = 0.0) -> None:
        self.voice_calls_attempted += 1
        self.last_call_time = time.time()
        if success:
            self.voice_calls_succeeded += 1
            self._total_call_duration += duration
        else:
            self.voice_calls_failed += 1

    def record_sms(self, success: bool) -> None:
        self.sms_sent += 1
        self.last_sms_time = time.time()
        if success:
            self.sms_succeeded += 1
        else:
            self.sms_failed += 1

    def record_fallback(self) -> None:
        self.fallback_used += 1

    def set_last_error(self, error: str) -> None:
        self.last_error = error

    def snapshot(self) -> dict[str, Any]:
        return {
            "voice_calls_attempted": self.voice_calls_attempted,
            "voice_calls_succeeded": self.voice_calls_succeeded,
            "voice_calls_failed": self.voice_calls_failed,
            "sms_sent": self.sms_sent,
            "sms_succeeded": self.sms_succeeded,
            "sms_failed": self.sms_failed,
            "fallback_used": self.fallback_used,
            "total_call_duration_seconds": int(self._total_call_duration),
            "last_call_time": self.last_call_time,
            "last_sms_time": self.last_sms_time,
            "last_error": self.last_error,
        }


_metrics = _CommMetrics()


def get_communication_metrics() -> dict[str, Any]:
    """Return current communication metrics snapshot."""
    return _metrics.snapshot()


def make_voice_call(
    destination_number: str,
    caller_number: str = "",
    message: str = "Hello.",
    *,
    has_approved_context: bool = False,
    callback_url: str | None = None,
    max_duration_seconds: int | None = None,
) -> dict[str, Any]:
    """Initiate an outbound voice call through the provider chain.

    Tries primary provider first. On NO_PROVIDER or NOT_CONFIGURED,
    falls back to the next provider in the chain.

    Returns a structured result dict suitable for capability execution.
    Never raises — errors are returned in the result.
    """
    # Policy check first
    policy = _policy.evaluate("make_phone_call", has_approved_context=has_approved_context)
    if policy.decision == PolicyDecision.DENIED:
        return {
            "status": "DENIED",
            "error": policy.reason,
            "policy": policy.reason,
        }
    if policy.decision == PolicyDecision.APPROVAL_REQUIRED:
        return {
            "status": "APPROVAL_REQUIRED",
            "error": policy.reason,
            "policy": policy.reason,
        }

    # Normalize destination number
    normalized_dest = normalize_e164(destination_number)
    if not normalized_dest:
        return {
            "status": "FAILED",
            "error": f"INVALID_DESTINATION: Cannot normalize '{destination_number}' to E.164",
        }

    chain = get_provider_chain()
    if not chain:
        _metrics.record_voice_call(False)
        _metrics.set_last_error("No provider configured")
        return {
            "status": "INTEGRATION_NOT_CONFIGURED",
            "error": (
                "INTEGRATION_NOT_CONFIGURED: no COMMUNICATION_PROVIDER or "
                "COMMUNICATION_PRIMARY_PROVIDER configured. "
                "Set COMMUNICATION_PROVIDER to 'twilio' or 'plivo' and "
                "configure the corresponding credentials."
            ),
        }

    last_result: dict[str, Any] | None = None
    for i, provider in enumerate(chain):
        if not provider.is_configured:
            logger.info(
                "Provider %s not configured, trying next", provider.config.provider
            )
            continue

        request = VoiceCallRequest(
            destination_number=normalized_dest,
            caller_number=caller_number or provider.config.from_number,
            message=message,
            callback_url=callback_url,
            max_duration_seconds=max_duration_seconds,
        )

        t0 = time.time()
        result: VoiceCallResponse = provider.make_voice_call(request)
        duration = time.time() - t0

        if i > 0:
            _metrics.record_fallback()

        # If the call succeeded (not failed/not_configured), return it
        if result.status not in (
            CallStatus.NO_PROVIDER,
            CallStatus.FAILED,
        ):
            _metrics.record_voice_call(True, duration or 0.0)
            return {
                "provider": result.provider,
                "call_id": result.call_id,
                "status": result.status.value,
                "error": result.error,
                "cost": result.cost,
                "duration_seconds": result.duration_seconds,
                "provider_metadata": result.provider_metadata,
                "fallback_used": i > 0,
            }

        # If it's a real error (not just "not configured"), record it
        if result.status == CallStatus.FAILED and result.error:
            last_result = {
                "provider": result.provider,
                "call_id": result.call_id,
                "status": result.status.value,
                "error": result.error,
                "cost": result.cost,
                "duration_seconds": result.duration_seconds,
                "provider_metadata": result.provider_metadata,
                "fallback_used": i > 0,
            }
            _metrics.record_voice_call(False)
            _metrics.set_last_error(result.error)
            # For NOT_CONFIGURED, try next provider; for real failure, stop
            if "INTEGRATION_NOT_CONFIGURED" not in (result.error or ""):
                return last_result

    # All providers exhausted
    if last_result:
        return last_result

    _metrics.record_voice_call(False)
    _metrics.set_last_error("All providers not configured")
    return {
        "status": "INTEGRATION_NOT_CONFIGURED",
        "error": (
            "INTEGRATION_NOT_CONFIGURED: all configured providers have missing credentials."
        ),
    }


def send_sms(
    destination_number: str,
    sender_number: str = "",
    message: str = "",
    *,
    has_approved_context: bool = False,
    callback_url: str | None = None,
) -> dict[str, Any]:
    """Send an outbound SMS through the provider chain.

    Tries primary provider first. On NO_PROVIDER or NOT_CONFIGURED,
    falls back to the next provider in the chain.

    Returns a structured result dict suitable for capability execution.
    Never raises — errors are returned in the result.
    """
    # Policy check first
    policy = _policy.evaluate("send_whatsapp", has_approved_context=has_approved_context)
    if policy.decision == PolicyDecision.DENIED:
        return {
            "status": "DENIED",
            "error": policy.reason,
            "policy": policy.reason,
        }
    if policy.decision == PolicyDecision.APPROVAL_REQUIRED:
        return {
            "status": "APPROVAL_REQUIRED",
            "error": policy.reason,
            "policy": policy.reason,
        }

    # Normalize destination number
    normalized_dest = normalize_e164(destination_number)
    if not normalized_dest:
        return {
            "status": "FAILED",
            "error": f"INVALID_DESTINATION: Cannot normalize '{destination_number}' to E.164",
        }

    chain = get_provider_chain()
    if not chain:
        _metrics.record_sms(False)
        _metrics.set_last_error("No provider configured")
        return {
            "status": "INTEGRATION_NOT_CONFIGURED",
            "error": (
                "INTEGRATION_NOT_CONFIGURED: no COMMUNICATION_PROVIDER or "
                "COMMUNICATION_PRIMARY_PROVIDER configured. "
                "Set COMMUNICATION_PROVIDER to 'twilio' or 'plivo' and "
                "configure the corresponding credentials."
            ),
        }

    last_result: dict[str, Any] | None = None
    for i, provider in enumerate(chain):
        if not provider.is_configured:
            logger.info(
                "Provider %s not configured, trying next", provider.config.provider
            )
            continue

        request = SmsRequest(
            destination_number=normalized_dest,
            sender_number=sender_number or provider.config.from_number,
            message=message,
            callback_url=callback_url,
        )

        result: SmsResponse = provider.send_sms(request)

        if i > 0:
            _metrics.record_fallback()

        if result.status not in (
            CommunicationStatus.NO_PROVIDER,
            CommunicationStatus.FAILED,
        ):
            _metrics.record_sms(True)
            return {
                "provider": result.provider,
                "message_id": result.message_id,
                "status": result.status.value,
                "error": result.error,
                "cost": result.cost,
                "provider_metadata": result.provider_metadata,
                "fallback_used": i > 0,
            }

        if result.status == CommunicationStatus.FAILED and result.error:
            last_result = {
                "provider": result.provider,
                "message_id": result.message_id,
                "status": result.status.value,
                "error": result.error,
                "cost": result.cost,
                "provider_metadata": result.provider_metadata,
                "fallback_used": i > 0,
            }
            _metrics.record_sms(False)
            _metrics.set_last_error(result.error)
            if "INTEGRATION_NOT_CONFIGURED" not in (result.error or ""):
                return last_result

    if last_result:
        return last_result

    _metrics.record_sms(False)
    _metrics.set_last_error("All providers not configured")
    return {
        "status": "INTEGRATION_NOT_CONFIGURED",
        "error": (
            "INTEGRATION_NOT_CONFIGURED: all configured providers have missing credentials."
        ),
    }


def is_configured() -> bool:
    """Check whether at least one communication provider is configured."""
    chain = get_provider_chain()
    return any(p.is_configured for p in chain)
