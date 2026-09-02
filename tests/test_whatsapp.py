"""Sprint 3 — WhatsApp Capability tests.

Comprehensive mocked tests for:
- WhatsApp models and E.164 normalization
- Provider interface (base adapter contract)
- OpenWA adapter (mocked HTTP)
- Provider factory (WHATSAPP_PROVIDER selection)
- WhatsApp service (policy enforcement, DB persistence, memory integration)
- Webhook parsing and processing
- Missing configuration (INTEGRATION_NOT_CONFIGURED)
- Invalid destination handling
- Secret redaction
- Capability definitions
- Action policy enforcement

NO REAL WHATSAPP MESSAGES during tests.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.whatsapp.base import BaseWhatsAppAdapter, WhatsAppConfig
from app.integrations.whatsapp.factory import (
    get_active_provider,
    get_config_summary,
    is_configured,
    list_available_providers,
)
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
    normalize_e164,
    redact_whatsapp_config,
)
from app.integrations.whatsapp.openwa_adapter import OpenWAAdapter
from app.services.whatsapp_service import send_message, process_inbound, get_provider_status


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_whatsapp_env():
    """Ensure no real credentials leak between tests."""
    env_keys = [
        "WHATSAPP_PROVIDER",
        "OPENWA_API_URL",
        "OPENWA_AUTH_TOKEN",
        "OPENWA_WEBHOOK_SECRET",
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


# ---------------------------------------------------------------------------
# 1. E.164 Normalization (WhatsApp)
# ---------------------------------------------------------------------------

class TestWhatsAppE164:
    def test_already_e164(self):
        assert normalize_e164("+15551234567") == "+15551234567"

    def test_us_without_plus(self):
        assert normalize_e164("15551234567") == "+15551234567"

    def test_india_e164(self):
        assert normalize_e164("+919876543210") == "+919876543210"

    def test_empty_string(self):
        assert normalize_e164("") == ""

    def test_letters_only(self):
        assert normalize_e164("abc") == ""


# ---------------------------------------------------------------------------
# 2. Models
# ---------------------------------------------------------------------------

class TestWhatsAppModels:
    def test_send_message_request_fields(self):
        req = SendMessageRequest(
            destination_number="+15551234567",
            message="Hello from GoalOS",
        )
        assert req.destination_number == "+15551234567"
        assert req.message == "Hello from GoalOS"
        assert req.media_type == WhatsAppMediaType.TEXT

    def test_send_message_request_with_media(self):
        req = SendMessageRequest(
            destination_number="+15551234567",
            media_url="https://example.com/image.jpg",
            media_type=WhatsAppMediaType.IMAGE,
            caption="Check this out",
        )
        assert req.media_url == "https://example.com/image.jpg"
        assert req.media_type == WhatsAppMediaType.IMAGE
        assert req.caption == "Check this out"

    def test_send_message_response_defaults(self):
        resp = SendMessageResponse(provider="openwa")
        assert resp.status == WhatsAppStatus.QUEUED
        assert resp.external_message_id is None
        assert resp.error is None

    def test_whatsapp_status_values(self):
        assert WhatsAppStatus.SENT.value == "sent"
        assert WhatsAppStatus.DELIVERED.value == "delivered"
        assert WhatsAppStatus.NO_PROVIDER.value == "no_provider"

    def test_media_type_values(self):
        assert WhatsAppMediaType.TEXT.value == "text"
        assert WhatsAppMediaType.IMAGE.value == "image"
        assert WhatsAppMediaType.VIDEO.value == "video"
        assert WhatsAppMediaType.DOCUMENT.value == "document"

    def test_webhook_event_type_values(self):
        assert WhatsAppWebhookEventType.MESSAGE_RECEIVED.value == "message.received"
        assert WhatsAppWebhookEventType.MESSAGE_DELIVERED.value == "message.delivered"

    def test_webhook_event_fields(self):
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="openwa",
            external_message_id="msg-123",
            status="message.received",
            sender_number="+15551234567",
        )
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_RECEIVED
        assert event.sender_number == "+15551234567"


# ---------------------------------------------------------------------------
# 3. Secret redaction
# ---------------------------------------------------------------------------

class TestWhatsAppRedaction:
    def test_long_value_masked(self):
        result = redact_whatsapp_config({"auth_token": "1234567890"})
        assert "****" in result["auth_token"]
        assert result["auth_token"] != "1234567890"

    def test_empty_value_preserved(self):
        result = redact_whatsapp_config({"key": ""})
        assert result["key"] == ""


# ---------------------------------------------------------------------------
# 4. WhatsAppConfig
# ---------------------------------------------------------------------------

class TestWhatsAppConfig:
    def test_configured_when_url_set(self):
        config = WhatsAppConfig(
            provider="openwa",
            api_base_url="http://localhost:5800",
        )
        assert config.is_configured is True

    def test_not_configured_when_url_empty(self):
        config = WhatsAppConfig(provider="openwa", api_base_url="")
        assert config.is_configured is False

    def test_redacted_config_masks_secrets(self):
        config = WhatsAppConfig(
            provider="openwa",
            api_base_url="http://localhost:5800",
            auth_token="secrettoken123456",
            webhook_secret="webhooksecret123",
        )
        masked = config.redacted()
        assert masked["provider"] == "openwa"
        assert "****" in masked["auth_token"]
        assert "****" in masked["webhook_secret"]


# ---------------------------------------------------------------------------
# 5. OpenWA Adapter (mocked)
# ---------------------------------------------------------------------------

class TestOpenWAAdapter:
    def _make_adapter(self, configured: bool = True) -> OpenWAAdapter:
        if configured:
            config = WhatsAppConfig(
                provider="openwa",
                api_base_url="http://localhost:5800",
                auth_token="test-token",
            )
        else:
            config = WhatsAppConfig(provider="openwa", api_base_url="")
        return OpenWAAdapter(config=config)

    def test_not_configured_returns_no_provider(self):
        adapter = self._make_adapter(configured=False)
        result = adapter.send_message(SendMessageRequest(
            destination_number="+15551234567", message="Hello"
        ))
        assert result.status == WhatsAppStatus.NO_PROVIDER
        assert "INTEGRATION_NOT_CONFIGURED" in result.error

    def test_invalid_number_returns_failed(self):
        adapter = self._make_adapter()
        result = adapter.send_message(SendMessageRequest(
            destination_number="abc", message="Hello"
        ))
        assert result.status == WhatsAppStatus.FAILED
        assert "INVALID_DESTINATION" in result.error

    def test_send_text_success(self):
        adapter = self._make_adapter()
        mock_response = {
            "messageId": "msg-123",
            "chatId": "15551234567@c.us",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567", message="Hello from GoalOS"
            ))
        assert result.provider == "openwa"
        assert result.external_message_id == "msg-123"
        assert result.status == WhatsAppStatus.SENT

    def test_send_text_api_error(self):
        adapter = self._make_adapter()
        mock_response = {"error": "Connection refused"}
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567", message="Hello"
            ))
        assert result.status == WhatsAppStatus.FAILED
        assert "PROVIDER_ERROR" in result.error

    def test_send_text_exception(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "_api_call", side_effect=ConnectionError("Timeout")):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567", message="Hello"
            ))
        assert result.status == WhatsAppStatus.FAILED
        assert "PROVIDER_EXCEPTION" in result.error

    def test_send_media_success(self):
        adapter = self._make_adapter()
        mock_response = {"messageId": "msg-media-123"}
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                media_url="https://example.com/photo.jpg",
                media_type=WhatsAppMediaType.IMAGE,
                caption="Check this",
            ))
        assert result.status == WhatsAppStatus.SENT
        # Verify media was included in the API call
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                media_url="https://example.com/photo.jpg",
                media_type=WhatsAppMediaType.IMAGE,
            ))
            body = mock_api.call_args[0][2]
            import json
            payload = json.loads(body.decode())
            assert "media" in payload
            assert payload["media"]["url"] == "https://example.com/photo.jpg"

    def test_parse_webhook_message_received(self):
        adapter = self._make_adapter()
        payload = {
            "event": "message",
            "messageId": "msg-456",
            "from": "+15551234567",
            "to": "+15559876543",
            "body": "Hello from customer",
            "chatId": "15551234567@c.us",
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_RECEIVED
        assert event.external_message_id == "msg-456"
        assert event.sender_number == "+15551234567"

    def test_parse_webhook_message_delivered(self):
        adapter = self._make_adapter()
        payload = {
            "event": "message.delivered",
            "messageId": "msg-789",
            "status": "delivered",
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_DELIVERED

    def test_parse_webhook_unknown_event(self):
        adapter = self._make_adapter()
        event = adapter.parse_webhook({"event": "unknown.event"})
        assert event is None

    def test_parse_webhook_empty_payload(self):
        adapter = self._make_adapter()
        event = adapter.parse_webhook({})
        assert event is None

    def test_verify_webhook_no_secret_accepts_all(self):
        adapter = self._make_adapter()
        assert adapter.verify_webhook(b"payload", "any-sig") is True

    def test_verify_webhook_with_secret_valid(self):
        import hashlib
        import hmac
        config = WhatsAppConfig(
            provider="openwa",
            api_base_url="http://localhost:5800",
            webhook_secret="my-secret",
        )
        adapter = OpenWAAdapter(config=config)
        payload = b"test payload"
        sig = hmac.new(b"my-secret", payload, hashlib.sha256).hexdigest()
        assert adapter.verify_webhook(payload, sig) is True

    def test_verify_webhook_with_secret_invalid(self):
        config = WhatsAppConfig(
            provider="openwa",
            api_base_url="http://localhost:5800",
            webhook_secret="my-secret",
        )
        adapter = OpenWAAdapter(config=config)
        assert adapter.verify_webhook(b"payload", "wrong-sig") is False

    def test_verify_webhook_with_secret_no_signature(self):
        config = WhatsAppConfig(
            provider="openwa",
            api_base_url="http://localhost:5800",
            webhook_secret="my-secret",
        )
        adapter = OpenWAAdapter(config=config)
        assert adapter.verify_webhook(b"payload", None) is False


# ---------------------------------------------------------------------------
# 6. Provider Factory
# ---------------------------------------------------------------------------

class TestWhatsAppFactory:
    def test_get_active_provider_none_when_empty(self):
        assert get_active_provider() is None

    def test_get_active_provider_openwa(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        provider = get_active_provider()
        assert provider is not None
        assert provider.name == "openwa"

    def test_list_available_providers(self):
        providers = list_available_providers()
        assert "openwa" in providers

    def test_is_configured_returns_true_when_valid(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        assert is_configured() is True

    def test_is_configured_returns_false_when_empty(self):
        assert is_configured() is False

    def test_get_config_summary_no_provider(self):
        summary = get_config_summary()
        assert summary["is_configured"] == "false"

    def test_get_config_summary_with_provider(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        os.environ["OPENWA_AUTH_TOKEN"] = "secret-token-12345"
        summary = get_config_summary()
        assert summary["provider"] == "openwa"
        assert "****" in summary.get("auth_token", "")


# ---------------------------------------------------------------------------
# 7. WhatsApp Service — Policy enforcement
# ---------------------------------------------------------------------------

class TestWhatsAppPolicyEnforcement:
    def test_send_message_denied_without_approval(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        result = send_message(
            destination_number="+15551234567",
            message="Test",
            has_approved_context=False,
        )
        assert result["status"] == "APPROVAL_REQUIRED"

    def test_send_message_with_approval_calls_provider(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        with patch("app.services.whatsapp_service._get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.name = "openwa"
            mock_provider.is_configured = True
            mock_provider.send_message.return_value = SendMessageResponse(
                provider="openwa",
                external_message_id="msg-123",
                status=WhatsAppStatus.SENT,
            )
            mock_get.return_value = mock_provider
            result = send_message(
                destination_number="+15551234567",
                message="Test with approval",
                has_approved_context=True,
            )
        assert result["status"] == "sent"
        assert result["external_message_id"] == "msg-123"


# ---------------------------------------------------------------------------
# 8. WhatsApp Service — Missing configuration
# ---------------------------------------------------------------------------

class TestWhatsAppMissingConfig:
    def test_no_provider_returns_not_configured(self):
        result = send_message(
            destination_number="+15551234567",
            message="Test",
            has_approved_context=True,
        )
        assert result["status"] == "INTEGRATION_NOT_CONFIGURED"

    def test_provider_not_configured_returns_not_configured(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        # OPENWA_API_URL not set
        result = send_message(
            destination_number="+15551234567",
            message="Test",
            has_approved_context=True,
        )
        assert result["status"] == "INTEGRATION_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# 9. WhatsApp Service — Invalid destination
# ---------------------------------------------------------------------------

class TestWhatsAppInvalidDestination:
    def test_invalid_number_returns_failed(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        with patch("app.services.whatsapp_service._get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.name = "openwa"
            mock_provider.is_configured = True
            mock_provider.send_message.return_value = SendMessageResponse(
                provider="openwa",
                status=WhatsAppStatus.FAILED,
                error="INVALID_DESTINATION: Cannot normalize 'abc' to E.164",
            )
            mock_get.return_value = mock_provider
            result = send_message(
                destination_number="abc",
                message="Test",
                has_approved_context=True,
            )
        assert result["status"] == "failed"
        assert "INVALID_DESTINATION" in result["error"]


# ---------------------------------------------------------------------------
# 10. Webhook processing (with mocked DB)
# ---------------------------------------------------------------------------

class TestWebhookProcessing:
    def test_process_inbound_message_received(self):
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="openwa",
            external_message_id="msg-inbound-123",
            status="message.received",
            sender_number="+15551234567",
            metadata={"body": "Hello from customer"},
        )
        mock_db = MagicMock()
        with patch("app.services.whatsapp_service.WhatsAppRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.get_or_create_contact.return_value = MagicMock(
                id=1, name="Customer", external_id="+15551234567"
            )
            mock_repo.get_or_create_conversation.return_value = MagicMock(id=1)
            mock_repo.create_message.return_value = MagicMock(id=1)
            result = process_inbound(event, db=mock_db)
        assert result["processed"] is True
        assert result["message_id"] == 1

    def test_process_inbound_delivered_event(self):
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_DELIVERED,
            provider="openwa",
            external_message_id="msg-456",
            status="delivered",
        )
        mock_db = MagicMock()
        with patch("app.services.whatsapp_service.WhatsAppRepository") as MockRepo:
            mock_repo = MagicMock()
            MockRepo.return_value = mock_repo
            mock_repo.update_message_status.return_value = MagicMock(id=1)
            result = process_inbound(event, db=mock_db)
        assert result["processed"] is True

    def test_process_inbound_no_db(self):
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="openwa",
            external_message_id="msg-123",
            status="message.received",
            sender_number="+15551234567",
        )
        result = process_inbound(event, db=None)
        assert result["processed"] is False
        assert "No database session" in result["error"]


# ---------------------------------------------------------------------------
# 11. Provider status
# ---------------------------------------------------------------------------

class TestProviderStatus:
    def test_status_no_provider(self):
        status = get_provider_status()
        assert status["configured"] is False

    def test_status_with_provider(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        status = get_provider_status()
        assert status["configured"] is True
        assert status["active_provider"] == "openwa"
        assert "openwa" in status["available_providers"]
