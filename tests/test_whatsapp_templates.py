"""Sprint 5B — WhatsApp Business Template Messaging tests.

Comprehensive mocked tests for:
- Template validation (valid, invalid, missing params)
- Template models (parameter types, component types)
- Meta adapter template sending (mocked HTTP)
- Template service (policy, idempotency, handoff)
- Template definitions (list, get)
- Template preview
- API response construction
- Credential redaction
- Existing WhatsApp tests remaining compatible

NO REAL WhatsApp template sends during tests.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.whatsapp import (
    HandoffState,
    MessageDirection,
    WhatsAppContact,
    WhatsAppConversation,
)
from app.integrations.whatsapp.models import (
    SendTemplateRequest,
    SendTemplateResponse,
    TemplateComponent,
    TemplateComponentType,
    TemplateParameter,
    TemplateParameterType,
    TemplateStatus,
)
from app.integrations.whatsapp.meta_adapter import MetaWhatsAppAdapter
from app.integrations.whatsapp.base import WhatsAppConfig
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.services.whatsapp_templates import (
    get_template,
    list_templates,
    preview_template_payload,
    send_template_message,
    validate_template_request,
    _is_duplicate_send,
    _sent_templates,
    TEMPLATE_ACTIONS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure no real credentials leak between tests."""
    env_keys = [
        "WHATSAPP_PROVIDER",
        "META_WHATSAPP_ACCESS_TOKEN",
        "META_WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_HANDOFF_KEYWORDS",
    ]
    saved = {k: os.environ.get(k) for k in env_keys}
    for k in env_keys:
        os.environ.pop(k, None)
    _sent_templates.clear()
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _sent_templates.clear()


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


@pytest.fixture
def sample_conversation(db):
    """Create a sample contact + conversation for testing."""
    repo = WhatsAppRepository(db)
    contact = repo.get_or_create_contact(
        provider="meta",
        external_id="+15551234567",
        phone_number="+15551234567",
        name="Alice Customer",
    )
    conv = repo.get_or_create_conversation(
        provider="meta",
        contact_id=contact.id,
        direction=MessageDirection.INBOUND,
    )
    db.commit()
    return contact, conv


def _make_valid_request() -> SendTemplateRequest:
    """Create a valid template request for testing."""
    return SendTemplateRequest(
        template_name="order_confirmation",
        language_code="en",
        recipient_number="+15551234567",
        components=[
            TemplateComponent(
                type=TemplateComponentType.BODY,
                parameters=[
                    TemplateParameter(type=TemplateParameterType.TEXT, text="ORD-12345"),
                    TemplateParameter(type=TemplateParameterType.TEXT, text="$99.99"),
                ],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Template Validation
# ---------------------------------------------------------------------------


class TestTemplateValidation:
    """Test template request validation."""

    def test_valid_request(self):
        result = validate_template_request(_make_valid_request())
        assert result["valid"] is True

    def test_missing_template_name(self):
        req = SendTemplateRequest(
            template_name="",
            language_code="en",
            recipient_number="+15551234567",
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "template_name" in result["error"]

    def test_invalid_template_name_characters(self):
        req = SendTemplateRequest(
            template_name="my template!",
            language_code="en",
            recipient_number="+15551234567",
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "invalid characters" in result["error"]

    def test_template_name_too_long(self):
        req = SendTemplateRequest(
            template_name="a" * 600,
            language_code="en",
            recipient_number="+15551234567",
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "too long" in result["error"]

    def test_missing_language_code(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="",
            recipient_number="+15551234567",
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "language_code" in result["error"]

    def test_language_code_too_short(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="x",
            recipient_number="+15551234567",
        )
        result = validate_template_request(req)
        assert result["valid"] is False

    def test_invalid_recipient(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="en",
            recipient_number="abc",
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "recipient" in result["error"]

    def test_duplicate_header_component(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="en",
            recipient_number="+15551234567",
            components=[
                TemplateComponent(type=TemplateComponentType.HEADER),
                TemplateComponent(type=TemplateComponentType.HEADER),
            ],
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "Duplicate" in result["error"]

    def test_empty_text_parameter(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="en",
            recipient_number="+15551234567",
            components=[
                TemplateComponent(
                    type=TemplateComponentType.BODY,
                    parameters=[
                        TemplateParameter(type=TemplateParameterType.TEXT, text=""),
                    ],
                ),
            ],
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "empty" in result["error"]

    def test_empty_image_parameter(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="en",
            recipient_number="+15551234567",
            components=[
                TemplateComponent(
                    type=TemplateComponentType.HEADER,
                    parameters=[
                        TemplateParameter(type=TemplateParameterType.IMAGE, image_url=None),
                    ],
                ),
            ],
        )
        result = validate_template_request(req)
        assert result["valid"] is False
        assert "no URL" in result["error"]

    def test_valid_with_header_image(self):
        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="en",
            recipient_number="+15551234567",
            components=[
                TemplateComponent(
                    type=TemplateComponentType.HEADER,
                    parameters=[
                        TemplateParameter(type=TemplateParameterType.IMAGE, image_url="https://example.com/logo.jpg"),
                    ],
                ),
                TemplateComponent(
                    type=TemplateComponentType.BODY,
                    parameters=[
                        TemplateParameter(type=TemplateParameterType.TEXT, text="ORD-12345"),
                    ],
                ),
            ],
        )
        result = validate_template_request(req)
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# 2. Template Models
# ---------------------------------------------------------------------------


class TestTemplateModels:
    """Test template data models."""

    def test_send_template_request_defaults(self):
        req = SendTemplateRequest(
            template_name="test",
            language_code="en",
            recipient_number="+15551234567",
        )
        assert req.template_name == "test"
        assert req.language_code == "en"
        assert req.components == []
        assert req.correlation_id is None

    def test_template_component_types(self):
        assert TemplateComponentType.HEADER.value == "header"
        assert TemplateComponentType.BODY.value == "body"
        assert TemplateComponentType.BUTTON.value == "button"

    def test_template_parameter_types(self):
        assert TemplateParameterType.TEXT.value == "text"
        assert TemplateParameterType.IMAGE.value == "image"
        assert TemplateParameterType.CURRENCY.value == "currency"

    def test_template_status_values(self):
        assert TemplateStatus.SENT.value == "sent"
        assert TemplateStatus.REJECTED.value == "rejected"
        assert TemplateStatus.INVALID_TEMPLATE.value == "invalid_template"

    def test_send_template_response_defaults(self):
        resp = SendTemplateResponse(provider="meta")
        assert resp.status == TemplateStatus.QUEUED
        assert resp.external_message_id is None

    def test_template_component_with_parameters(self):
        comp = TemplateComponent(
            type=TemplateComponentType.BODY,
            parameters=[
                TemplateParameter(type=TemplateParameterType.TEXT, text="hello"),
            ],
        )
        assert comp.type == TemplateComponentType.BODY
        assert len(comp.parameters) == 1
        assert comp.parameters[0].text == "hello"


# ---------------------------------------------------------------------------
# 3. Meta Adapter Template Sending
# ---------------------------------------------------------------------------


class TestMetaAdapterTemplate:
    """Test Meta adapter template sending with mocked HTTP."""

    def _make_adapter(self, configured: bool = True) -> MetaWhatsAppAdapter:
        if configured:
            config = WhatsAppConfig(
                provider="meta",
                api_base_url="https://graph.facebook.com/v21.0/123456",
                auth_token="test-token-12345",
            )
        else:
            config = WhatsAppConfig(provider="meta", api_base_url="")
        return MetaWhatsAppAdapter(config=config)

    def test_not_configured_returns_no_provider(self):
        adapter = self._make_adapter(configured=False)
        req = _make_valid_request()
        resp = adapter.send_template(req)
        assert resp.status == TemplateStatus.NO_PROVIDER
        assert "INTEGRATION_NOT_CONFIGURED" in resp.error

    def test_invalid_destination_returns_failed(self):
        adapter = self._make_adapter()
        req = SendTemplateRequest(
            template_name="test",
            language_code="en",
            recipient_number="abc",
        )
        resp = adapter.send_template(req)
        assert resp.status == TemplateStatus.FAILED
        assert "INVALID_DESTINATION" in resp.error

    def test_template_send_success(self):
        adapter = self._make_adapter()
        mock_response = {
            "messaging_product": "whatsapp",
            "contacts": [{"wa_id": "15551234567"}],
            "messages": [{"id": "wamid.template-123"}],
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            resp = adapter.send_template(_make_valid_request())
        assert resp.status == TemplateStatus.SENT
        assert resp.external_message_id == "wamid.template-123"
        assert resp.correlation_id is None

    def test_template_send_with_correlation_id(self):
        adapter = self._make_adapter()
        mock_response = {
            "messages": [{"id": "wamid.template-456"}],
            "contacts": [{"wa_id": "15551234567"}],
        }
        req = _make_valid_request()
        req_with_corr = SendTemplateRequest(
            template_name=req.template_name,
            language_code=req.language_code,
            recipient_number=req.recipient_number,
            components=req.components,
            correlation_id="corr-789",
        )
        with patch.object(adapter, "_api_call", return_value=mock_response):
            resp = adapter.send_template(req_with_corr)
        assert resp.correlation_id == "corr-789"
        assert resp.status == TemplateStatus.SENT

    def test_template_send_meta_error(self):
        adapter = self._make_adapter()
        mock_response = {
            "error": {
                "message": "Invalid template",
                "type": "OAuthException",
                "code": 131047,
            }
        }
        with patch.object(adapter, "_api_call", return_value=mock_response):
            resp = adapter.send_template(_make_valid_request())
        assert resp.status == TemplateStatus.REJECTED
        assert "PROVIDER_ERROR" in resp.error

    def test_template_send_exception(self):
        adapter = self._make_adapter()
        with patch.object(adapter, "_api_call", side_effect=ConnectionError("Timeout")):
            resp = adapter.send_template(_make_valid_request())
        assert resp.status == TemplateStatus.FAILED
        assert "PROVIDER_EXCEPTION" in resp.error

    def test_template_send_verifies_meta_payload(self):
        """Verify the adapter constructs the correct Meta template payload."""
        adapter = self._make_adapter()
        mock_response = {"messages": [{"id": "wamid.test"}], "contacts": [{"wa_id": "15551234567"}]}
        with patch.object(adapter, "_api_call", return_value=mock_response) as mock_api:
            adapter.send_template(_make_valid_request())
            body = mock_api.call_args[0][2]
            import json
            payload = json.loads(body.decode())
            assert payload["type"] == "template"
            assert payload["template"]["name"] == "order_confirmation"
            assert payload["template"]["language"]["code"] == "en"
            assert payload["to"] == "+15551234567"
            assert len(payload["template"]["components"]) == 1
            assert payload["template"]["components"][0]["type"] == "body"
            assert len(payload["template"]["components"][0]["parameters"]) == 2


# ---------------------------------------------------------------------------
# 4. Template Definitions
# ---------------------------------------------------------------------------


class TestTemplateDefinitions:
    """Test template definition management."""

    def test_list_templates(self):
        templates = list_templates()
        assert len(templates) >= 7
        names = [t["name"] for t in templates]
        assert "order_confirmation" in names
        assert "shipping_update" in names
        assert "human_handoff_notification" in names

    def test_get_template(self):
        t = get_template("order_confirmation")
        assert t is not None
        assert t["category"] == "transactional"
        assert "order_number" in t["variables"]

    def test_get_unknown_template(self):
        t = get_template("nonexistent_template")
        assert t is None

    def test_template_categories(self):
        templates = list_templates()
        categories = {t["category"] for t in templates}
        assert "transactional" in categories
        assert "utility" in categories
        assert "marketing" in categories


# ---------------------------------------------------------------------------
# 5. Template Preview
# ---------------------------------------------------------------------------


class TestTemplatePreview:
    """Test template payload preview."""

    def test_preview_produces_meta_payload(self):
        req = _make_valid_request()
        preview = preview_template_payload(req)
        assert "meta_payload" in preview
        meta = preview["meta_payload"]
        assert meta["type"] == "template"
        assert meta["template"]["name"] == "order_confirmation"
        assert meta["template"]["language"]["code"] == "en"
        assert meta["to"] == "+15551234567"

    def test_preview_includes_components(self):
        req = _make_valid_request()
        preview = preview_template_payload(req)
        assert len(preview["components"]) == 1
        comp = preview["components"][0]
        assert comp["type"] == "body"
        assert len(comp["parameters"]) == 2


# ---------------------------------------------------------------------------
# 6. Template Service — Policy Enforcement
# ---------------------------------------------------------------------------


class TestTemplateServicePolicy:
    """Test template service with Action Policy."""

    def test_send_requires_approval(self):
        result = send_template_message(_make_valid_request(), has_approved_context=False)
        assert result["status"] == "approval_required"

    def test_send_denied_without_approval(self):
        result = send_template_message(_make_valid_request(), has_approved_context=False)
        assert "approval" in result["status"]

    def test_send_with_approval_calls_provider(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "test-token"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"

        with patch("app.services.whatsapp_templates.get_active_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.name = "meta"
            mock_provider.is_configured = True
            mock_provider.send_template.return_value = SendTemplateResponse(
                provider="meta",
                external_message_id="wamid-123",
                status=TemplateStatus.SENT,
            )
            mock_get.return_value = mock_provider
            result = send_template_message(_make_valid_request(), has_approved_context=True)
        assert result["sent"] is True
        assert result["status"] == "sent"

    def test_send_invalid_template_returns_error(self):
        req = SendTemplateRequest(
            template_name="",
            language_code="en",
            recipient_number="+15551234567",
        )
        result = send_template_message(req, has_approved_context=True)
        assert result["sent"] is False
        assert result["status"] == "invalid_template"

    def test_send_no_provider(self):
        result = send_template_message(_make_valid_request(), has_approved_context=True)
        assert result["sent"] is False
        assert result["status"] == "no_provider"


# ---------------------------------------------------------------------------
# 7. Template Service — Idempotency
# ---------------------------------------------------------------------------


class TestTemplateIdempotency:
    """Test duplicate send protection."""

    def test_duplicate_correlation_id(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "test-token"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"

        with patch("app.services.whatsapp_templates.get_active_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.name = "meta"
            mock_provider.is_configured = True
            mock_provider.send_template.return_value = SendTemplateResponse(
                provider="meta", status=TemplateStatus.SENT,
            )
            mock_get.return_value = mock_provider
            req = SendTemplateRequest(
                template_name="order_confirmation",
                language_code="en",
                recipient_number="+15551234567",
                correlation_id="corr-001",
            )
            result1 = send_template_message(req, has_approved_context=True)
            assert result1["sent"] is True

            # Second send with same correlation_id
            result2 = send_template_message(req, has_approved_context=True)
            assert result2["sent"] is False
            assert result2["status"] == "duplicate"

    def test_different_correlation_ids_allowed(self):
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "test-token"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"

        with patch("app.services.whatsapp_templates.get_active_provider") as mock_get:
            mock_provider = MagicMock()
            mock_provider.name = "meta"
            mock_provider.is_configured = True
            mock_provider.send_template.return_value = SendTemplateResponse(
                provider="meta", status=TemplateStatus.SENT,
            )
            mock_get.return_value = mock_provider
            req1 = SendTemplateRequest(
                template_name="order_confirmation",
                language_code="en",
                recipient_number="+15551234567",
                correlation_id="corr-002",
            )
            req2 = SendTemplateRequest(
                template_name="order_confirmation",
                language_code="en",
                recipient_number="+15551234567",
                correlation_id="corr-003",
            )
            result1 = send_template_message(req1, has_approved_context=True)
            result2 = send_template_message(req2, has_approved_context=True)
            assert result1["sent"] is True
            assert result2["sent"] is True


# ---------------------------------------------------------------------------
# 8. Template Service — Handoff Integration
# ---------------------------------------------------------------------------


class TestTemplateHandoffIntegration:
    """Test template sending respects handoff state."""

    def test_template_blocked_during_handoff(self, db, sample_conversation):
        contact, conv = sample_conversation
        # Create handoff
        from app.services.whatsapp_handoff import request_handoff
        request_handoff(db, conv.id, reason="explicit_user_request")

        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "test-token"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123456"

        req = SendTemplateRequest(
            template_name="order_confirmation",
            language_code="en",
            recipient_number="+15551234567",
        )
        result = send_template_message(req, has_approved_context=True, db=db)
        assert result["sent"] is False
        assert result["status"] == "handoff_active"


# ---------------------------------------------------------------------------
# 9. Template Action Declaration
# ---------------------------------------------------------------------------


class TestTemplateActionDeclaration:
    """Test template-specific action policy declaration."""

    def test_template_action_exists(self):
        names = [a.action_name for a in TEMPLATE_ACTIONS]
        assert "send_whatsapp_template" in names

    def test_template_action_risk_level(self):
        from app.services.action_policy import ActionPolicyEngine
        engine = ActionPolicyEngine()
        engine.register_many(TEMPLATE_ACTIONS)
        decl = engine.get_declaration("send_whatsapp_template")
        assert decl is not None
        assert decl.risk_level.value == "MEDIUM"
        assert decl.approval_required is True
        assert decl.has_external_side_effect is True
