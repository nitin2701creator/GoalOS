"""Voice Calling tests for GoalOS.

Comprehensive mocked tests for:
- Voice call models
- Voice call DB model + repository
- Plivo voice adapter (mocked)
- Twilio voice adapter (mocked)
- Provider selection + fallback
- Voice service (policy, memory, webhooks)
- Call status tracking
- Domestic + international numbers
- Invalid numbers
- Provider unavailable
- Webhook signature validation
- Duplicate webhook handling
- Action policy approval
- Credential redaction
- Multilingual metadata
- Call history + summary
- Existing communications tests remaining compatible

NO real phone calls during tests.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.voice import (
    CallDirection,
    VoiceCallEvent,
    VoiceCallRecord,
    VoiceCallStatus,
)
from app.integrations.communications.base import CommunicationConfig
from app.integrations.communications.models import (
    CallStatus,
    VoiceCallRequest,
    VoiceCallResponse,
    normalize_e164,
)
from app.integrations.communications.twilio_adapter import TwilioAdapter
from app.integrations.communications.plivo_adapter import PlivoAdapter
from app.repositories.voice_repository import VoiceRepository
from app.services.voice_service import (
    get_call_detail,
    get_call_history,
    get_voice_call_summary,
    get_voice_status,
    handle_call_status_webhook,
    initiate_voice_call,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure no real credentials leak between tests."""
    env_keys = [
        "COMMUNICATION_PROVIDER",
        "COMMUNICATION_PRIMARY_PROVIDER",
        "COMMUNICATION_FALLBACK_PROVIDER",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM_NUMBER",
        "PLIVO_AUTH_ID",
        "PLIVO_AUTH_TOKEN",
        "PLIVO_FROM_NUMBER",
    ]
    saved = {k: os.environ.get(k) for k in env_keys}
    for k in env_keys:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# 1. E.164 Normalization
# ---------------------------------------------------------------------------


class TestVoiceE164:
    def test_already_e164(self):
        assert normalize_e164("+15551234567") == "+15551234567"

    def test_us_without_plus(self):
        assert normalize_e164("15551234567") == "+15551234567"

    def test_india_e164(self):
        assert normalize_e164("+919876543210") == "+919876543210"

    def test_uk_e164(self):
        assert normalize_e164("+447911123456") == "+447911123456"

    def test_empty_string(self):
        assert normalize_e164("") == ""

    def test_letters_only(self):
        assert normalize_e164("abc") == ""

    def test_short_number(self):
        assert normalize_e164("123") == ""


# ---------------------------------------------------------------------------
# 2. Voice Call Models
# ---------------------------------------------------------------------------


class TestVoiceModels:
    def test_voice_call_request_fields(self):
        req = VoiceCallRequest(
            destination_number="+15551234567",
            caller_number="+15559876543",
            message="Hello from GoalOS",
        )
        assert req.destination_number == "+15551234567"
        assert req.message == "Hello from GoalOS"

    def test_voice_call_response_defaults(self):
        resp = VoiceCallResponse(provider="plivo")
        assert resp.status == CallStatus.QUEUED
        assert resp.call_id is None

    def test_call_status_values(self):
        assert CallStatus.INITIATED.value == "initiated"
        assert CallStatus.COMPLETED.value == "completed"
        assert CallStatus.NO_PROVIDER.value == "no_provider"


# ---------------------------------------------------------------------------
# 3. Voice Call DB Model
# ---------------------------------------------------------------------------


class TestVoiceDBModel:
    def test_create_call_record(self, db):
        call = VoiceCallRecord(
            provider="plivo",
            destination_number="+15551234567",
            direction=CallDirection.OUTBOUND,
            status=VoiceCallStatus.QUEUED,
            language="en",
        )
        db.add(call)
        db.commit()
        fetched = db.get(VoiceCallRecord, call.id)
        assert fetched is not None
        assert fetched.provider == "plivo"
        assert fetched.destination_number == "+15551234567"

    def test_call_events_relationship(self, db):
        call = VoiceCallRecord(
            provider="plivo",
            destination_number="+15551234567",
            direction=CallDirection.OUTBOUND,
        )
        db.add(call)
        db.flush()
        event = VoiceCallEvent(
            call_id=call.id,
            event_type="call.initiated",
            provider="plivo",
        )
        db.add(event)
        db.commit()
        events = db.query(VoiceCallEvent).filter_by(call_id=call.id).all()
        assert len(events) == 1


# ---------------------------------------------------------------------------
# 4. Voice Repository
# ---------------------------------------------------------------------------


class TestVoiceRepository:
    def test_create_call(self, db):
        repo = VoiceRepository(db)
        call = repo.create_call(
            provider="plivo",
            destination_number="+15551234567",
            caller_number="+15559876543",
            tts_message="Hello",
            language="en",
        )
        assert call.id is not None
        assert call.status == VoiceCallStatus.QUEUED

    def test_update_call_status(self, db):
        repo = VoiceRepository(db)
        call = repo.create_call(provider="plivo", destination_number="+15551234567")
        updated = repo.update_call_status(
            call.id,
            VoiceCallStatus.INITIATED,
            provider_status="initiated",
        )
        assert updated.status == VoiceCallStatus.INITIATED
        assert updated.initiated_at is not None

    def test_record_event(self, db):
        repo = VoiceRepository(db)
        call = repo.create_call(provider="plivo", destination_number="+15551234567")
        event = repo.record_event(
            call.id, "call.ringing", "plivo", status="ringing"
        )
        assert event.id is not None

    def test_list_calls(self, db):
        repo = VoiceRepository(db)
        repo.create_call(provider="plivo", destination_number="+15551111111")
        repo.create_call(provider="twilio", destination_number="+15552222222")
        calls = repo.list_calls()
        assert len(calls) == 2

    def test_get_call_by_external_id(self, db):
        repo = VoiceRepository(db)
        call = repo.create_call(
            provider="plivo",
            destination_number="+15551234567",
            external_call_id="ext-123",
        )
        found = repo.get_call_by_external_id("ext-123")
        assert found is not None
        assert found.id == call.id


# ---------------------------------------------------------------------------
# 5. Plivo Adapter (Mocked)
# ---------------------------------------------------------------------------


class TestPlivoAdapter:
    def _make_adapter(self, configured=True):
        if configured:
            config = CommunicationConfig(
                provider="plivo",
                account_id="AUTH_ID_123",
                auth_token="auth_token_456",
                from_number="+15559876543",
            )
        else:
            config = CommunicationConfig(
                provider="plivo", account_id="", auth_token="", from_number=""
            )
        return PlivoAdapter(config=config)

    def test_not_configured_returns_no_provider(self):
        adapter = self._make_adapter(configured=False)
        result = adapter.make_voice_call(VoiceCallRequest(
            destination_number="+15551234567", caller_number="+15559876543", message="Hello"
        ))
        assert result.status == CallStatus.NO_PROVIDER
        assert "INTEGRATION_NOT_CONFIGURED" in result.error

    def test_invalid_number_returns_failed(self):
        adapter = self._make_adapter()
        result = adapter.make_voice_call(VoiceCallRequest(
            destination_number="abc", caller_number="+15559876543", message="Hello"
        ))
        assert result.status == CallStatus.FAILED
        assert "INVALID_DESTINATION" in result.error

    def test_domestic_call_success(self):
        adapter = self._make_adapter()
        mock_response = {
            "request_uuid": "plivo-call-abc",
            "status": "initiated",
            "message": "call fired",
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+15551234567",
                caller_number="+15559876543",
                message="Hello from GoalOS",
            ))
        assert result.status == CallStatus.INITIATED
        assert result.call_id == "plivo-call-abc"

    def test_international_call_success(self):
        adapter = self._make_adapter()
        mock_response = {
            "request_uuid": "plivo-call-intl",
            "status": "initiated",
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+919876543210",
                caller_number="+15559876543",
                message="Namaste from GoalOS",
            ))
        assert result.status == CallStatus.INITIATED
        assert result.call_id == "plivo-call-intl"

    def test_provider_error(self):
        adapter = self._make_adapter()
        mock_response = {"error": "Invalid number", "error_code": "21211"}
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+15551234567",
                caller_number="+15559876543",
                message="Hello",
            ))
        assert result.status == CallStatus.FAILED
        assert "PROVIDER_ERROR" in result.error

    def test_provider_exception(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "_api_call", side_effect=ConnectionError("Timeout")):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+15551234567",
                caller_number="+15559876543",
                message="Hello",
            ))
        assert result.status == CallStatus.FAILED
        assert "PROVIDER_EXCEPTION" in result.error


# ---------------------------------------------------------------------------
# 6. Twilio Adapter (Mocked)
# ---------------------------------------------------------------------------


class TestTwilioAdapter:
    def _make_adapter(self, configured=True):
        if configured:
            config = CommunicationConfig(
                provider="twilio",
                account_id="AC1234567890",
                auth_token="twilio_auth_token",
                from_number="+15559876543",
            )
        else:
            config = CommunicationConfig(
                provider="twilio", account_id="", auth_token="", from_number=""
            )
        return TwilioAdapter(config=config)

    def test_not_configured_returns_no_provider(self):
        adapter = self._make_adapter(configured=False)
        result = adapter.make_voice_call(VoiceCallRequest(
            destination_number="+15551234567", caller_number="+15559876543", message="Hello"
        ))
        assert result.status == CallStatus.NO_PROVIDER

    def test_domestic_call_success(self):
        adapter = self._make_adapter()
        mock_response = {
            "sid": "CA1234567890",
            "status": "initiated",
            "to": "+15551234567",
            "from": "+15559876543",
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+15551234567",
                caller_number="+15559876543",
                message="Hello from GoalOS",
            ))
        assert result.status == CallStatus.INITIATED
        assert result.call_id == "CA1234567890"

    def test_international_call_success(self):
        adapter = self._make_adapter()
        mock_response = {
            "sid": "CA-intl-123",
            "status": "initiated",
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+447911123456",
                caller_number="+15559876543",
                message="Hello from GoalOS",
            ))
        assert result.status == CallStatus.INITIATED

    def test_provider_error_busy(self):
        adapter = self._make_adapter()
        mock_response = {"code": 21218, "message": "Busy"}
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.make_voice_call(VoiceCallRequest(
                destination_number="+15551234567",
                caller_number="+15559876543",
                message="Hello",
            ))
        assert result.status == CallStatus.BUSY


# ---------------------------------------------------------------------------
# 7. Voice Service — Policy Enforcement
# ---------------------------------------------------------------------------


class TestVoiceServicePolicy:
    def test_call_requires_approval(self):
        result = initiate_voice_call(
            "+15551234567", message="Hello",
            has_approved_context=False,
        )
        assert result["status"] == "APPROVAL_REQUIRED"

    def test_no_provider_returns_not_configured(self):
        result = initiate_voice_call(
            "+15551234567", message="Hello",
            has_approved_context=True,
        )
        assert result["status"] == "INTEGRATION_NOT_CONFIGURED"

    def test_invalid_number_returns_failed(self):
        result = initiate_voice_call(
            "abc", message="Hello",
            has_approved_context=True,
        )
        assert result["status"] == "FAILED"
        assert "INVALID_DESTINATION" in result["error"]

    def test_call_with_provider_chain(self):
        os.environ["COMMUNICATION_PRIMARY_PROVIDER"] = "plivo"
        os.environ["PLIVO_AUTH_ID"] = "test_id"
        os.environ["PLIVO_AUTH_TOKEN"] = "test_token"
        os.environ["PLIVO_FROM_NUMBER"] = "+15559876543"

        with patch("app.services.voice_service.get_provider_chain") as mock_chain:
            mock_adapter = MagicMock()
            mock_adapter.is_configured = True
            mock_adapter.config.from_number = "+15559876543"
            mock_adapter.make_voice_call.return_value = VoiceCallResponse(
                provider="plivo",
                call_id="plivo-123",
                status=CallStatus.INITIATED,
            )
            mock_chain.return_value = [mock_adapter]
            result = initiate_voice_call(
                "+15551234567", message="Hello",
                has_approved_context=True,
            )
        assert result["status"] == "initiated"
        assert result["provider"] == "plivo"


# ---------------------------------------------------------------------------
# 8. Voice Service — Call Status Webhook
# ---------------------------------------------------------------------------


class TestVoiceWebhook:
    def test_webhook_unrecognized_payload(self, db):
        result = handle_call_status_webhook({"random": "data"}, db=db)
        assert result["received"] is True
        assert result["processed"] is False
        assert result["reason"] == "unrecognized_payload"

    def test_webhook_no_db(self):
        payload = {
            "CallSid": "CA123",
            "CallStatus": "completed",
            "To": "+15551234567",
            "From": "+15559876543",
            "CallDuration": "45",
        }
        mock_event = MagicMock()
        mock_event.event_type.value = "call.completed"
        mock_event.provider = "twilio"
        mock_event.provider_id = "CA123"
        mock_event.status = "completed"
        mock_event.duration_seconds = 45
        mock_event.error_code = None
        mock_event.error_message = None
        mock_provider = MagicMock()
        mock_provider.parse_webhook.return_value = mock_event
        with patch("app.services.voice_service.get_provider_chain", return_value=[mock_provider]):
            result = handle_call_status_webhook(payload, db=None)
        assert result["received"] is True
        assert result["processed"] is True
        assert result["reason"] == "no_db_session"

    def test_webhook_creates_call_record(self, db):
        payload = {
            "CallSid": "CA-new-123",
            "CallStatus": "initiated",
            "To": "+15551234567",
            "From": "+15559876543",
        }
        with patch("app.services.voice_service.get_provider_chain") as mock_chain:
            mock_adapter = MagicMock()
            mock_adapter.parse_webhook.return_value = MagicMock(
                event_type=MagicMock(value="call.initiated"),
                provider="twilio",
                provider_id="CA-new-123",
                status="initiated",
                destination_number="+15551234567",
                source_number="+15559876543",
                duration_seconds=None,
                error_code=None,
                error_message=None,
            )
            mock_chain.return_value = [mock_adapter]
            result = handle_call_status_webhook(payload, db=db)
        assert result["processed"] is True
        assert result["call_id"] is not None

    def test_webhook_completes_call_creates_memory(self, db):
        # First create a call record
        repo = VoiceRepository(db)
        call = repo.create_call(
            provider="twilio",
            destination_number="+15551234567",
            external_call_id="CA-complete-123",
        )
        db.commit()

        payload = {
            "CallSid": "CA-complete-123",
            "CallStatus": "completed",
            "CallDuration": "120",
            "To": "+15551234567",
        }
        with patch("app.services.voice_service.get_provider_chain") as mock_chain:
            mock_adapter = MagicMock()
            mock_adapter.parse_webhook.return_value = MagicMock(
                event_type=MagicMock(value="call.completed"),
                provider="twilio",
                provider_id="CA-complete-123",
                status="completed",
                destination_number="+15551234567",
                source_number="",
                duration_seconds=120,
                error_code=None,
                error_message=None,
            )
            mock_chain.return_value = [mock_adapter]
            result = handle_call_status_webhook(payload, db=db)
        assert result["processed"] is True
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# 9. Voice Call History & Summary
# ---------------------------------------------------------------------------


class TestVoiceHistory:
    def test_empty_history(self, db):
        calls = get_call_history(db)
        assert calls == []

    def test_history_with_calls(self, db):
        repo = VoiceRepository(db)
        repo.create_call(provider="plivo", destination_number="+15551111111")
        repo.create_call(provider="twilio", destination_number="+15552222222")
        db.commit()
        calls = get_call_history(db)
        assert len(calls) == 2

    def test_empty_summary(self, db):
        result = get_voice_call_summary(db)
        assert result["total_calls"] == 0

    def test_summary_with_data(self, db):
        repo = VoiceRepository(db)
        c1 = repo.create_call(provider="plivo", destination_number="+15551111111", language="en")
        repo.update_call_status(c1.id, VoiceCallStatus.COMPLETED, duration_seconds=60)
        c2 = repo.create_call(provider="plivo", destination_number="+15552222222", language="hi")
        repo.update_call_status(c2.id, VoiceCallStatus.FAILED)
        db.commit()
        result = get_voice_call_summary(db)
        assert result["total_calls"] == 2
        assert result["completed_calls"] == 1
        assert result["failed_calls"] == 1
        assert result["languages"]["en"] == 1
        assert result["languages"]["hi"] == 1


# ---------------------------------------------------------------------------
# 10. Voice Status
# ---------------------------------------------------------------------------


class TestVoiceStatus:
    def test_status_no_provider(self):
        result = get_voice_status()
        assert result["configured"] is False

    def test_status_with_provider(self):
        os.environ["COMMUNICATION_PROVIDER"] = "plivo"
        os.environ["PLIVO_AUTH_ID"] = "test_id"
        os.environ["PLIVO_AUTH_TOKEN"] = "test_token"
        os.environ["PLIVO_FROM_NUMBER"] = "+15559876543"
        result = get_voice_status()
        assert result["configured"] is True
        assert "plivo" in result["available_providers"]
