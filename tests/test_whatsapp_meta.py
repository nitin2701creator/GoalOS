"""Sprint 4A — Meta WhatsApp Cloud API Adapter tests.

Comprehensive mocked tests for:
- Meta text/image/video/audio/document messaging
- Webhook verification (valid/invalid/challenge)
- Incoming message normalization
- Delivery/read/failed status normalization
- Invalid credentials / missing configuration
- API failure / rate limiting
- Provider selection (WHATSAPP_PROVIDER=meta)
- Action Policy enforcement
- Credential redaction

NO REAL META API REQUESTS during tests.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.whatsapp.base import WhatsAppConfig
from app.integrations.whatsapp.factory import (
    get_active_provider,
    get_config_summary,
    is_configured,
    list_available_providers,
)
from app.integrations.whatsapp.meta_adapter import MetaWhatsAppAdapter, meta_config_from_env
from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)
from app.services.whatsapp_service import send_message, get_provider_status


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_meta_env():
    """Ensure no real credentials leak between tests."""
    env_keys = [
        "WHATSAPP_PROVIDER",
        "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
        "META_WHATSAPP_BUSINESS_ACCOUNT_ID",
        "META_WHATSAPP_VERIFY_TOKEN",
        "META_WHATSAPP_APP_SECRET",
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


def _make_adapter(configured: bool = True) -> MetaWhatsAppAdapter:
    if configured:
        config = WhatsAppConfig(
            provider="meta",
            api_base_url="https://graph.facebook.com/v21.0/123456",
            auth_token="test-access-token",
            webhook_secret="test-app-secret",
            extra={
                "phone_number_id": "123456",
                "business_account_id": "789012",
                "verify_token": "test-verify-token",
            },
        )
    else:
        config = WhatsAppConfig(provider="meta", api_base_url="")
    return MetaWhatsAppAdapter(config=config)


# ---------------------------------------------------------------------------
# 1. Meta Text Message
# ---------------------------------------------------------------------------

class TestMetaTextMessage:
    def test_send_text_success(self):
        adapter = _make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.abc123"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                message="Hello from GoalOS",
            ))
        assert result.provider == "meta"
        assert result.external_message_id == "wamid.abc123"
        assert result.status == WhatsAppStatus.SENT
        assert result.provider_metadata["wa_id"] == "15551234567"

    def test_send_text_normalized_number(self):
        adapter = _make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.def456"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            adapter.send_message(SendMessageRequest(
                destination_number="5551234567",
                message="Hello US local",
            ))
            body = mock_api.call_args[0][2]
            payload = json.loads(body.decode())
            assert payload["to"] == "+15551234567"


# ---------------------------------------------------------------------------
# 2. Meta Media Messages
# ---------------------------------------------------------------------------

class TestMetaMediaMessages:
    def test_send_image_success(self):
        adapter = _make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.img123"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                media_url="https://example.com/photo.jpg",
                media_type=WhatsAppMediaType.IMAGE,
                caption="Check this out",
            ))
            body = mock_api.call_args[0][2]
            payload = json.loads(body.decode())
            assert payload["type"] == "image"
            assert payload["image"]["link"] == "https://example.com/photo.jpg"
            assert payload["image"]["caption"] == "Check this out"
        assert result.status == WhatsAppStatus.SENT
        assert result.external_message_id == "wamid.img123"

    def test_send_video_success(self):
        adapter = _make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.vid123"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                media_url="https://example.com/video.mp4",
                media_type=WhatsAppMediaType.VIDEO,
                caption="Video caption",
            ))
            body = mock_api.call_args[0][2]
            payload = json.loads(body.decode())
            assert payload["type"] == "video"
            assert payload["video"]["link"] == "https://example.com/video.mp4"
            assert payload["video"]["caption"] == "Video caption"
        assert result.status == WhatsAppStatus.SENT

    def test_send_audio_success(self):
        adapter = _make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.aud123"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                media_url="https://example.com/audio.mp3",
                media_type=WhatsAppMediaType.AUDIO,
            ))
            body = mock_api.call_args[0][2]
            payload = json.loads(body.decode())
            assert payload["type"] == "audio"
            assert payload["audio"]["link"] == "https://example.com/audio.mp3"
            # Audio does not support captions
            assert "caption" not in payload["audio"]
        assert result.status == WhatsAppStatus.SENT

    def test_send_document_success(self):
        adapter = _make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.doc123"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567",
                media_url="https://example.com/file.pdf",
                media_type=WhatsAppMediaType.DOCUMENT,
                caption="Invoice",
            ))
            body = mock_api.call_args[0][2]
            payload = json.loads(body.decode())
            assert payload["type"] == "document"
            assert payload["document"]["link"] == "https://example.com/file.pdf"
            assert payload["document"]["caption"] == "Invoice"
        assert result.status == WhatsAppStatus.SENT

    def test_unsupported_media_type(self):
        adapter = _make_adapter()
        result = adapter.send_message(SendMessageRequest(
            destination_number="+15551234567",
            media_url="https://example.com/sticker.webp",
            media_type=WhatsAppMediaType.STICKER,
        ))
        assert result.status == WhatsAppStatus.FAILED
        assert "UNSUPPORTED_MEDIA_TYPE" in result.error


# ---------------------------------------------------------------------------
# 3. Webhook Verification
# ---------------------------------------------------------------------------

class TestMetaWebhookVerification:
    def test_verify_webhook_valid_signature(self):
        adapter = _make_adapter()
        payload = b'{"object":"whatsapp_business_account"}'
        secret = "test-app-secret"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert adapter.verify_webhook(payload, f"sha256={sig}") is True

    def test_verify_webhook_invalid_signature(self):
        adapter = _make_adapter()
        assert adapter.verify_webhook(b'payload', "sha256=invalidhash") is False

    def test_verify_webhook_no_signature(self):
        adapter = _make_adapter()
        assert adapter.verify_webhook(b'payload', None) is False

    def test_verify_webhook_no_secret_accepts_all(self):
        config = WhatsAppConfig(provider="meta", api_base_url="http://test", auth_token="tok")
        adapter = MetaWhatsAppAdapter(config=config)
        assert adapter.verify_webhook(b'payload', "sha256=anything") is True

    def test_webhook_challenge_valid_token(self):
        adapter = _make_adapter()
        challenge = adapter.verify_webhook_challenge(
            mode="subscribe", token="test-verify-token", challenge="random123"
        )
        assert challenge == "random123"

    def test_webhook_challenge_invalid_token(self):
        adapter = _make_adapter()
        challenge = adapter.verify_webhook_challenge(
            mode="subscribe", token="wrong-token", challenge="random123"
        )
        assert challenge is None

    def test_webhook_challenge_wrong_mode(self):
        adapter = _make_adapter()
        challenge = adapter.verify_webhook_challenge(
            mode="unsubscribe", token="test-verify-token", challenge="random123"
        )
        assert challenge is None

    def test_webhook_challenge_no_verify_token(self):
        config = WhatsAppConfig(provider="meta", api_base_url="http://test")
        adapter = MetaWhatsAppAdapter(config=config)
        challenge = adapter.verify_webhook_challenge(
            mode="subscribe", token="any", challenge="random123"
        )
        assert challenge is None


# ---------------------------------------------------------------------------
# 4. Webhook Parsing — Incoming Messages
# ---------------------------------------------------------------------------

class TestMetaWebhookParsing:
    def test_parse_incoming_text_message(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WABA_ID",
                "changes": [{
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {"phone_number_id": "123456"},
                        "messages": [{
                            "from": "15551234567",
                            "id": "wamid.inbound123",
                            "timestamp": "1700000000",
                            "type": "text",
                            "text": {"body": "Hello GoalOS"},
                        }],
                    },
                    "field": "messages",
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_RECEIVED
        assert event.external_message_id == "wamid.inbound123"
        assert event.sender_number == "15551234567"
        assert event.metadata["type"] == "text"
        assert event.metadata["body"] == "Hello GoalOS"

    def test_parse_incoming_image_message(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "id": "WABA_ID",
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "15551234567",
                            "id": "wamid.img456",
                            "timestamp": "1700000000",
                            "type": "image",
                            "image": {
                                "link": "https://example.com/photo.jpg",
                                "caption": "Nice photo",
                            },
                        }],
                    },
                    "field": "messages",
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.metadata["type"] == "image"
        assert event.metadata["media_url"] == "https://example.com/photo.jpg"
        assert event.metadata["body"] == "Nice photo"

    def test_parse_incoming_video_message(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "15551234567",
                            "id": "wamid.vid789",
                            "type": "video",
                            "video": {"link": "https://example.com/video.mp4"},
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.metadata["type"] == "video"
        assert event.metadata["media_url"] == "https://example.com/video.mp4"

    def test_parse_incoming_location_message(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "15551234567",
                            "id": "wamid.loc123",
                            "type": "location",
                            "location": {"latitude": "37.7749", "longitude": "-122.4194"},
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert "37.7749" in event.metadata["body"]

    def test_parse_non_whatsapp_object(self):
        adapter = _make_adapter()
        event = adapter.parse_webhook({"object": "page"})
        assert event is None

    def test_parse_empty_entries(self):
        adapter = _make_adapter()
        event = adapter.parse_webhook({"object": "whatsapp_business_account", "entry": []})
        assert event is None

    def test_parse_no_messages_no_statuses(self):
        adapter = _make_adapter()
        event = adapter.parse_webhook({
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"value": {}}]}],
        })
        assert event is None


# ---------------------------------------------------------------------------
# 5. Webhook Parsing — Status Updates
# ---------------------------------------------------------------------------

class TestMetaStatusUpdates:
    def test_parse_delivered_status(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.delivered123",
                            "status": "delivered",
                            "timestamp": "1700000000",
                            "recipient_id": "15551234567",
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_DELIVERED
        assert event.external_message_id == "wamid.delivered123"
        assert event.destination_number == "15551234567"

    def test_parse_read_status(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.read456",
                            "status": "read",
                            "timestamp": "1700000000",
                            "recipient_id": "15551234567",
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_READ

    def test_parse_sent_status(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.sent789",
                            "status": "sent",
                            "timestamp": "1700000000",
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_SENT

    def test_parse_failed_status(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.fail000",
                            "status": "failed",
                            "timestamp": "1700000000",
                            "errors": [{
                                "code": 131026,
                                "message": "Message undeliverable",
                            }],
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is not None
        assert event.event_type == WhatsAppWebhookEventType.MESSAGE_FAILED
        assert event.error_code == "131026"
        assert event.error_message == "Message undeliverable"

    def test_parse_unknown_status(self):
        adapter = _make_adapter()
        payload = {
            "object": "whatsapp_business_account",
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{
                            "id": "wamid.unknown",
                            "status": "unknown_status",
                        }],
                    },
                }],
            }],
        }
        event = adapter.parse_webhook(payload)
        assert event is None


# ---------------------------------------------------------------------------
# 6. Missing Configuration
# ---------------------------------------------------------------------------

class TestMetaMissingConfig:
    def test_not_configured_returns_no_provider(self):
        adapter = _make_adapter(configured=False)
        result = adapter.send_message(SendMessageRequest(
            destination_number="+15551234567", message="Hello"
        ))
        assert result.status == WhatsAppStatus.NO_PROVIDER
        assert "INTEGRATION_NOT_CONFIGURED" in result.error

    def test_invalid_number_returns_failed(self):
        adapter = _make_adapter()
        result = adapter.send_message(SendMessageRequest(
            destination_number="abc", message="Hello"
        ))
        assert result.status == WhatsAppStatus.FAILED
        assert "INVALID_DESTINATION" in result.error

    def test_no_provider_configured(self):
        result = send_message(
            destination_number="+15551234567",
            message="Test",
            has_approved_context=True,
        )
        assert result["status"] == "INTEGRATION_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# 7. API Failures
# ---------------------------------------------------------------------------

class TestMetaAPIFailures:
    def test_api_error_response(self):
        adapter = _make_adapter()
        mock_response = {
            "error": {
                "message": "Invalid OAuth access token",
                "type": "OAuthException",
                "code": 190,
                "error_subcode": 102,
                "fbtrace_id": "trace123",
            }
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567", message="Hello"
            ))
        assert result.status == WhatsAppStatus.FAILED
        assert "PROVIDER_ERROR" in result.error
        assert "190" in result.error

    def test_api_exception(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_api_call", side_effect=ConnectionError("Timeout")):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567", message="Hello"
            ))
        assert result.status == WhatsAppStatus.FAILED
        assert "PROVIDER_EXCEPTION" in result.error

    def test_rate_limit_error(self):
        adapter = _make_adapter()
        mock_response = {
            "error": {
                "message": "Rate limit hit",
                "type": "HTTPException",
                "code": 368,
            }
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            result = adapter.send_message(SendMessageRequest(
                destination_number="+15551234567", message="Hello"
            ))
        assert result.status == WhatsAppStatus.FAILED
        assert "368" in result.error


# ---------------------------------------------------------------------------
# 8. Provider Selection
# ---------------------------------------------------------------------------

class TestMetaProviderSelection:
    def test_meta_provider_in_registry(self):
        providers = list_available_providers()
        assert "meta" in providers
        assert "openwa" in providers

    def test_select_meta_provider(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "token123"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        provider = get_active_provider()
        assert provider is not None
        assert provider.name == "meta"

    def test_is_configured_meta(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "token123"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        assert is_configured() is True

    def test_get_config_summary_meta(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "secret-token-12345"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        summary = get_config_summary()
        assert summary["provider"] == "meta"
        assert "****" in summary.get("auth_token", "")

    def test_select_openwa_provider(self):
        os.environ["WHATSAPP_PROVIDER"] = "openwa"
        os.environ["OPENWA_API_URL"] = "http://localhost:5800"
        provider = get_active_provider()
        assert provider is not None
        assert provider.name == "openwa"


# ---------------------------------------------------------------------------
# 9. Action Policy Enforcement
# ---------------------------------------------------------------------------

class TestMetaActionPolicy:
    def test_send_message_requires_approval(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "token123"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        result = send_message(
            destination_number="+15551234567",
            message="Test",
            has_approved_context=False,
        )
        assert result["status"] == "APPROVAL_REQUIRED"

    def test_send_message_with_approval(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "token123"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        with patch("app.services.whatsapp_service._get_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.name = "meta"
            mock_provider.is_configured = True
            mock_provider.send_message.return_value = SendMessageResponse(
                provider="meta",
                external_message_id="wamid.approved123",
                status=WhatsAppStatus.SENT,
            )
            mock_get.return_value = mock_provider
            result = send_message(
                destination_number="+15551234567",
                message="Approved message",
                has_approved_context=True,
            )
        assert result["status"] == "sent"
        assert result["external_message_id"] == "wamid.approved123"


# ---------------------------------------------------------------------------
# 10. Credential Redaction
# ---------------------------------------------------------------------------

class TestMetaCredentialRedaction:
    def test_config_redacts_secrets(self):
        adapter = _make_adapter()
        redacted = adapter.config.redacted()
        assert redacted["provider"] == "meta"
        assert "****" in redacted["auth_token"]
        assert "****" in redacted["webhook_secret"]
        assert redacted["auth_token"] != "test-access-token"
        assert redacted["webhook_secret"] != "test-app-secret"

    def test_status_no_secret_leak(self):
        adapter = _make_adapter()
        status = adapter.get_status()
        # Status should have metadata but not tokens
        assert "access_token" not in json.dumps(status)
        assert "test-access-token" not in json.dumps(status)

    def test_provider_status_no_secrets(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "secret-token-12345"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"
        status = get_provider_status()
        assert "secret-token" not in json.dumps(status)


# ---------------------------------------------------------------------------
# 11. Provider Status
# ---------------------------------------------------------------------------

class TestMetaProviderStatus:
    def test_status_not_configured(self):
        adapter = _make_adapter(configured=False)
        status = adapter.get_status()
        assert status["configured"] is False
        assert status["status"] == "not_configured"

    def test_status_configured(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_api_call", return_value={"verified_name": "GoalOS"}):
            status = adapter.get_status()
        assert status["configured"] is True
        assert status["phone_number_id"] == "123456"
        assert status["business_account_id"] == "789012"

    def test_status_api_unreachable(self):
        adapter = _make_adapter()
        with patch.object(adapter, "_api_call", side_effect=Exception("timeout")):
            status = adapter.get_status()
        assert status["configured"] is True
        assert status.get("api_reachable") is False
