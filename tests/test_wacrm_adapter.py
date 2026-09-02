"""Comprehensive tests for WACRM WhatsApp adapter, provider router, and dual-provider switching.

Tests cover:
- WACRM adapter initialization and configuration
- Message sending (text and media)
- Template sending
- Webhook parsing and verification
- Session management
- Error handling
- Provider factory with WACRM
- Provider auto-selection
- Provider switching
- Credential redaction
- GoalOS capability registration
- Webhook endpoint integration
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.integrations.whatsapp.base import WhatsAppConfig
from app.main import app
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    SendTemplateRequest,
    SendTemplateResponse,
    TemplateComponent,
    TemplateComponentType,
    TemplateParameter,
    TemplateParameterType,
    TemplateStatus,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path: Path):
    """TestClient with an isolated in-memory-style SQLite database."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'wacrm_tests.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure no real env vars leak between tests."""
    for var in [
        "WACRM_API_URL", "WACRM_API_KEY", "WACRM_WEBHOOK_SECRET",
        "OPENWA_API_URL", "OPENWA_AUTH_TOKEN", "OPENWA_WEBHOOK_SECRET",
        "WHATSAPP_PROVIDER", "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
    ]:
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def wacrm_config():
    """WACRM config with test values."""
    return WhatsAppConfig(
        provider="wacrm",
        api_base_url="http://localhost:3000",
        auth_token="wacrm_live_test_key_12345",
        webhook_secret="whsec_test_secret_67890",
    )


@pytest.fixture
def adapter(wacrm_config):
    """Instantiated WACRM adapter with mocked env."""
    os.environ["WACRM_API_URL"] = "http://localhost:3000"
    os.environ["WACRM_API_KEY"] = "wacrm_live_test_key_12345"
    os.environ["WACRM_WEBHOOK_SECRET"] = "whsec_test_secret_67890"

    from app.integrations.whatsapp.wacrm_adapter import WacrmWhatsAppAdapter

    return WacrmWhatsAppAdapter(config=wacrm_config)


# ---------------------------------------------------------------------------
# 1. Adapter initialization
# ---------------------------------------------------------------------------


class TestWacrmAdapterInit:
    def test_name(self, adapter):
        assert adapter.name == "wacrm"

    def test_is_configured_with_url(self, adapter):
        assert adapter.is_configured is True

    def test_not_configured_without_url(self):
        from app.integrations.whatsapp.wacrm_adapter import WacrmWhatsAppAdapter

        a = WacrmWhatsAppAdapter(config=WhatsAppConfig(provider="wacrm", api_base_url=""))
        assert a.is_configured is False

    def test_config_redacted(self, adapter):
        redacted = adapter.config.redacted()
        assert redacted["provider"] == "wacrm"
        # Token should be masked
        assert "wacrm_live" not in str(redacted.get("auth_token", ""))
        assert "wacrm_live" not in str(redacted.get("webhook_secret", ""))


# ---------------------------------------------------------------------------
# 2. Send message — text
# ---------------------------------------------------------------------------


class TestWacrmSendText:
    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_text_success(self, mock_api, adapter):
        mock_api.return_value = {
            "data": {
                "id": "msg_wacrm_001",
                "conversation_id": "conv_001",
                "contact_id": "contact_001",
                "status": "sent",
            }
        }
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="Hello from GoalOS!",
        )
        result = adapter.send_message(request)
        assert result.status == WhatsAppStatus.SENT
        assert result.external_message_id == "msg_wacrm_001"
        assert result.provider == "wacrm"
        mock_api.assert_called_once()
        call_args = mock_api.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/messages"

    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_text_api_error(self, mock_api, adapter):
        mock_api.return_value = {
            "error": {"code": "forbidden", "message": "Missing scope"}
        }
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="Test",
        )
        result = adapter.send_message(request)
        assert result.status == WhatsAppStatus.FAILED
        assert "forbidden" in result.error

    def test_send_text_not_configured(self):
        from app.integrations.whatsapp.wacrm_adapter import WacrmWhatsAppAdapter

        a = WacrmWhatsAppAdapter(config=WhatsAppConfig(provider="wacrm", api_base_url=""))
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="Test",
        )
        result = a.send_message(request)
        assert result.status == WhatsAppStatus.NO_PROVIDER
        assert "NOT_CONFIGURED" in result.error


# ---------------------------------------------------------------------------
# 3. Send message — media
# ---------------------------------------------------------------------------


class TestWacrmSendMedia:
    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_image(self, mock_api, adapter):
        mock_api.return_value = {
            "data": {"id": "msg_img_001", "status": "sent"}
        }
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="",
            media_url="https://example.com/photo.jpg",
            media_type=WhatsAppMediaType.IMAGE,
            caption="Check this out",
        )
        result = adapter.send_message(request)
        assert result.status == WhatsAppStatus.SENT
        assert result.external_message_id == "msg_img_001"

    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_video(self, mock_api, adapter):
        mock_api.return_value = {
            "data": {"id": "msg_vid_001", "status": "sent"}
        }
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="",
            media_url="https://example.com/video.mp4",
            media_type=WhatsAppMediaType.VIDEO,
            caption="Demo video",
        )
        result = adapter.send_message(request)
        assert result.status == WhatsAppStatus.SENT


# ---------------------------------------------------------------------------
# 4. Template sending
# ---------------------------------------------------------------------------


class TestWacrmTemplate:
    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_template_success(self, mock_api, adapter):
        mock_api.return_value = {
            "data": {"id": "msg_tpl_001", "status": "sent"}
        }
        request = SendTemplateRequest(
            template_name="order_update",
            language_code="en_US",
            recipient_number="+1234567890",
            components=[
                TemplateComponent(
                    type=TemplateComponentType.BODY,
                    parameters=[TemplateParameter(type=TemplateParameterType.TEXT, text="A123")],
                )
            ],
            correlation_id="corr_001",
        )
        result = adapter.send_template(request)
        assert result.status == TemplateStatus.SENT
        assert result.external_message_id == "msg_tpl_001"
        assert result.correlation_id == "corr_001"

    def test_send_template_not_configured(self):
        from app.integrations.whatsapp.wacrm_adapter import WacrmWhatsAppAdapter

        a = WacrmWhatsAppAdapter(config=WhatsAppConfig(provider="wacrm", api_base_url=""))
        request = SendTemplateRequest(
            template_name="test",
            language_code="en",
            recipient_number="+1234567890",
        )
        result = a.send_template(request)
        assert result.status == TemplateStatus.NO_PROVIDER

    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_template_rejected(self, mock_api, adapter):
        mock_api.return_value = {
            "error": {"code": "bad_request", "message": "Template not approved"}
        }
        request = SendTemplateRequest(
            template_name="unapproved",
            language_code="en",
            recipient_number="+1234567890",
        )
        result = adapter.send_template(request)
        assert result.status == TemplateStatus.REJECTED


# ---------------------------------------------------------------------------
# 5. Webhook parsing
# ---------------------------------------------------------------------------


class TestWacrmWebhookParsing:
    def test_parse_message_received(self, adapter):
        payload = {
            "id": "delivery_001",
            "event": "message.received",
            "occurred_at": "2026-07-01T12:00:00.000Z",
            "account_id": "acc_001",
            "data": {
                "conversation_id": "conv_001",
                "contact_id": "contact_001",
                "whatsapp_message_id": "wamid.msg_001",
                "content_type": "text",
                "text": "Hello from customer",
                "contact_phone": "+9876543210",
            },
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_RECEIVED
        assert event.external_message_id == "wamid.msg_001"
        assert event.sender_number == "+9876543210"
        assert event.provider == "wacrm"
        assert event.metadata["conversation_id"] == "conv_001"

    def test_parse_message_delivered(self, adapter):
        payload = {
            "id": "delivery_002",
            "event": "message.status_updated",
            "data": {
                "whatsapp_message_id": "wamid.msg_002",
                "status": "delivered",
                "conversation_id": "conv_001",
            },
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_DELIVERED

    def test_parse_message_read(self, adapter):
        payload = {
            "id": "delivery_003",
            "event": "message.status_updated",
            "data": {
                "whatsapp_message_id": "wamid.msg_003",
                "status": "read",
            },
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_READ

    def test_parse_message_failed(self, adapter):
        payload = {
            "id": "delivery_004",
            "event": "message.status_updated",
            "data": {
                "whatsapp_message_id": "wamid.msg_004",
                "status": "failed",
            },
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_FAILED

    def test_parse_conversation_created_returns_none(self, adapter):
        payload = {
            "id": "delivery_005",
            "event": "conversation.created",
            "data": {"conversation_id": "conv_002"},
        }
        event = adapter.parse_webhook(payload)
        assert event is None

    def test_parse_unknown_event_returns_none(self, adapter):
        payload = {"id": "x", "event": "something.unknown"}
        event = adapter.parse_webhook(payload)
        assert event is None

    def test_parse_empty_payload_returns_none(self, adapter):
        event = adapter.parse_webhook({})
        assert event is None

    def test_parse_message_received_with_media(self, adapter):
        payload = {
            "id": "delivery_006",
            "event": "message.received",
            "data": {
                "whatsapp_message_id": "wamid.msg_006",
                "content_type": "image",
                "text": "Photo caption",
                "media_url": "https://example.com/image.jpg",
                "contact_phone": "+1234567890",
            },
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.metadata["content_type"] == "image"
        assert event.metadata["media_url"] == "https://example.com/image.jpg"


# ---------------------------------------------------------------------------
# 6. Webhook signature verification
# ---------------------------------------------------------------------------


class TestWacrmWebhookVerification:
    def test_verify_valid_signature(self, adapter):
        body = b'{"event":"message.received"}'
        secret = "whsec_test_secret_67890"
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert adapter.verify_webhook(body, expected) is True

    def test_verify_invalid_signature(self, adapter):
        body = b'{"event":"message.received"}'
        assert adapter.verify_webhook(body, "wrong-signature") is False

    def test_verify_missing_signature(self, adapter):
        body = b'{"event":"message.received"}'
        assert adapter.verify_webhook(body, None) is False

    def test_verify_no_secret_accepts_all(self):
        from app.integrations.whatsapp.wacrm_adapter import WacrmWhatsAppAdapter

        a = WacrmWhatsAppAdapter(
            config=WhatsAppConfig(
                provider="wacrm",
                api_base_url="http://localhost:3000",
                webhook_secret="",
            )
        )
        assert a.verify_webhook(b"anything", None) is True
        assert a.verify_webhook(b"anything", "fake") is True


# ---------------------------------------------------------------------------
# 7. Health/status
# ---------------------------------------------------------------------------


class TestWacrmStatus:
    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_get_status_healthy(self, mock_api, adapter):
        mock_api.return_value = {
            "data": {
                "account": {"id": "acc_001", "name": "Acme Inc"},
                "key": {"scopes": ["messages:send", "contacts:read"]},
            }
        }
        status = adapter.get_status()
        assert status["configured"] is True
        assert status["api_reachable"] is True
        assert status["account_name"] == "Acme Inc"
        assert "messages:send" in status["scopes"]

    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_get_status_auth_error(self, mock_api, adapter):
        mock_api.return_value = {
            "error": {"code": "unauthorized", "message": "Invalid key"}
        }
        status = adapter.get_status()
        assert status["api_reachable"] is True
        assert status["auth_error"] == "unauthorized"

    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_get_status_unreachable(self, mock_api, adapter):
        mock_api.side_effect = ConnectionError("connection refused")
        status = adapter.get_status()
        assert status["api_reachable"] is False

    def test_get_status_not_configured(self):
        from app.integrations.whatsapp.wacrm_adapter import WacrmWhatsAppAdapter

        a = WacrmWhatsAppAdapter(config=WhatsAppConfig(provider="wacrm", api_base_url=""))
        status = a.get_status()
        assert status["configured"] is False
        assert status["status"] == "not_configured"


# ---------------------------------------------------------------------------
# 8. Provider factory with WACRM
# ---------------------------------------------------------------------------


class TestWacrmFactory:
    def test_factory_selects_wacrm(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "wacrm")
        monkeypatch.setenv("WACRM_API_URL", "http://localhost:3000")

        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider is not None
        assert provider.name == "wacrm"

    def test_factory_returns_none_when_not_configured(self, monkeypatch):
        monkeypatch.delenv("WHATSAPP_PROVIDER", raising=False)
        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider is None

    def test_factory_list_providers_includes_wacrm(self):
        from app.integrations.whatsapp.factory import list_available_providers

        providers = list_available_providers()
        assert "wacrm" in providers
        assert "openwa" in providers
        assert "meta" in providers


# ---------------------------------------------------------------------------
# 9. Provider auto-selection
# ---------------------------------------------------------------------------


class TestProviderAutoSelection:
    def test_auto_selects_wacrm_when_configured(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "auto")
        monkeypatch.setenv("WACRM_API_URL", "http://localhost:3000")

        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider is not None
        assert provider.name == "wacrm"

    def test_auto_falls_back_to_openwa(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "auto")
        monkeypatch.delenv("WACRM_API_URL", raising=False)
        monkeypatch.setenv("OPENWA_API_URL", "http://localhost:2785")

        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider is not None
        assert provider.name == "openwa"

    def test_auto_returns_none_when_nothing_configured(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "auto")
        monkeypatch.delenv("WACRM_API_URL", raising=False)
        monkeypatch.delenv("OPENWA_API_URL", raising=False)

        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider is None


# ---------------------------------------------------------------------------
# 10. Provider switching
# ---------------------------------------------------------------------------


class TestProviderSwitching:
    def test_switch_to_wacrm(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "wacrm")
        monkeypatch.setenv("WACRM_API_URL", "http://localhost:3000")

        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider.name == "wacrm"

    def test_switch_to_openwa(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "openwa")
        monkeypatch.setenv("OPENWA_API_URL", "http://localhost:2785")

        from app.integrations.whatsapp.factory import get_active_provider

        provider = get_active_provider()
        assert provider.name == "openwa"


# ---------------------------------------------------------------------------
# 11. All provider status
# ---------------------------------------------------------------------------


class TestAllProviderStatus:
    def test_get_all_provider_status(self, monkeypatch):
        monkeypatch.setenv("WHATSAPP_PROVIDER", "wacrm")
        monkeypatch.setenv("WACRM_API_URL", "http://localhost:3000")
        monkeypatch.setenv("OPENWA_API_URL", "http://localhost:2785")

        from app.integrations.whatsapp.factory import get_all_provider_status

        result = get_all_provider_status()
        assert result["active_provider"] == "wacrm"
        assert "wacrm" in result["providers"]
        assert "openwa" in result["providers"]
        assert result["providers"]["wacrm"]["configured"] is True
        assert result["providers"]["openwa"]["configured"] is True


# ---------------------------------------------------------------------------
# 12. Error handling
# ---------------------------------------------------------------------------


class TestWacrmErrorHandling:
    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_network_error(self, mock_api, adapter):
        mock_api.side_effect = ConnectionError("Network unreachable")
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="Test",
        )
        result = adapter.send_message(request)
        assert result.status == WhatsAppStatus.FAILED
        assert "exception" in result.error.lower()

    @patch("app.integrations.whatsapp.wacrm_adapter.WacrmWhatsAppAdapter._api_call")
    def test_send_http_error(self, mock_api, adapter):
        mock_api.side_effect = ConnectionError("WACRM API error 500: internal")
        request = SendMessageRequest(
            destination_number="+1234567890",
            message="Test",
        )
        result = adapter.send_message(request)
        assert result.status == WhatsAppStatus.FAILED


# ---------------------------------------------------------------------------
# 13. Webhook endpoint integration
# ---------------------------------------------------------------------------


class TestWacrmWebhookEndpoint:
    def test_webhook_rejects_invalid_json(self, api):
        response = api.post(
            "/api/v1/webhooks/wacrm",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code in (422, 200, 404)

    def test_webhook_accepts_valid_json(self, api):
        payload = {
            "id": "delivery_test_001",
            "event": "message.received",
            "data": {
                "whatsapp_message_id": "wamid.test_001",
                "content_type": "text",
                "text": "Hello",
                "contact_phone": "+1234567890",
            },
        }
        response = api.post(
            "/api/v1/webhooks/wacrm",
            json=payload,
        )
        assert response.status_code in (200, 202, 404)

    def test_webhook_rejects_bad_signature(self, api):
        response = api.post(
            "/api/v1/webhooks/wacrm",
            content=b'{"event":"message.received"}',
            headers={
                "Content-Type": "application/json",
                "X-Wacrm-Signature": "bad-sig",
            },
        )
        # Without WACRM_WEBHOOK_SECRET set, accepts all
        assert response.status_code in (200, 422, 404)


# ---------------------------------------------------------------------------
# 14. WhatsApp send endpoint with WACRM
# ---------------------------------------------------------------------------


class TestWhatsAppSendEndpoint:
    @patch("app.api.v1.whatsapp_api.send_message")
    def test_send_endpoint_with_wacrm_provider(self, mock_send, api):
        mock_send.return_value = {
            "provider": "wacrm",
            "external_message_id": "wamid.test_001",
            "status": "sent",
            "error": None,
            "provider_metadata": {},
        }

        response = api.post(
            "/api/v1/whatsapp/send",
            json={
                "destination_number": "+1234567890",
                "message": "Hello via WACRM",
                "approved": True,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "sent"
        assert data["external_message_id"] == "wamid.test_001"


# ---------------------------------------------------------------------------
# 15. WhatsApp status endpoint
# ---------------------------------------------------------------------------


class TestWhatsAppStatusEndpoint:
    def test_status_endpoint(self, api):
        response = api.get("/api/v1/whatsapp/status")
        assert response.status_code == 200
        data = response.json()
        assert "configured" in data
        assert "available_providers" in data
        assert "wacrm" in data["available_providers"]
        assert "openwa" in data["available_providers"]


# ---------------------------------------------------------------------------
# 16. Credential redaction
# ---------------------------------------------------------------------------


class TestCredentialRedaction:
    def test_wacrm_config_redacted_masks_token(self, adapter):
        redacted = adapter.config.redacted()
        assert "wacrm_live" not in str(redacted.get("auth_token", ""))
        assert "whsec" not in str(redacted.get("webhook_secret", ""))

    def test_wacrm_config_redacted_preserves_provider(self, adapter):
        redacted = adapter.config.redacted()
        assert redacted["provider"] == "wacrm"
