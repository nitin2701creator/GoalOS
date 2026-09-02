"""Sprint 4B — WhatsApp AI Auto-Reply Agent tests.

Comprehensive mocked tests for:
- Inbound WhatsApp message processing
- Memory retrieval for contact context
- AI response generation
- Outbound WhatsApp reply
- Conversation isolation (no cross-contact memory leaks)
- Duplicate webhook idempotency
- Provider failure handling
- Malformed/missing webhooks
- Action Policy enforcement
- Auto-reply disabled mode
- Agent status/configuration
- LLM fallback when unavailable

NO REAL WHATSAPP MESSAGES or LLM CALLS during tests.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.whatsapp.models import (
    WhatsAppMediaType,
    WhatsAppStatus,
    WhatsAppWebhookEvent,
    WhatsAppWebhookEventType,
)
from app.services.whatsapp_agent import (
    _is_auto_reply_enabled,
    _is_duplicate,
    _retrieve_contact_memory,
    _generate_response,
    get_agent_status,
    handle_inbound_message,
    _processed_messages,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_agent_env():
    """Ensure clean environment between tests."""
    env_keys = [
        "WHATSAPP_AUTO_REPLY_ENABLED",
        "WHATSAPP_AGENT_SYSTEM_PROMPT",
        "LLM_PROVIDER",
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
    # Clear idempotency cache
    _processed_messages.clear()


def _make_inbound_event(
    message_id: str = "wamid.test123",
    sender: str = "+15551234567",
    content: str = "Hello GoalOS",
) -> WhatsAppWebhookEvent:
    return WhatsAppWebhookEvent(
        event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
        provider="meta",
        external_message_id=message_id,
        status="received",
        sender_number=sender,
        metadata={"body": content, "type": "text"},
    )


# ---------------------------------------------------------------------------
# 1. Auto-reply Enabled/Disabled
# ---------------------------------------------------------------------------

class TestAutoReplyConfig:
    def test_disabled_by_default(self):
        assert _is_auto_reply_enabled() is False

    def test_enabled_with_true(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        assert _is_auto_reply_enabled() is True

    def test_enabled_with_1(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "1"
        assert _is_auto_reply_enabled() is True

    def test_enabled_with_yes(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "yes"
        assert _is_auto_reply_enabled() is True

    def test_disabled_with_false(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "false"
        assert _is_auto_reply_enabled() is False


# ---------------------------------------------------------------------------
# 2. Idempotency
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_first_message_not_duplicate(self):
        assert _is_duplicate("wamid.unique123") is False

    def test_same_message_is_duplicate(self):
        _is_duplicate("wamid.dup456")
        assert _is_duplicate("wamid.dup456") is True

    def test_empty_message_id_not_duplicate(self):
        assert _is_duplicate("") is False
        assert _is_duplicate(None) is False  # type: ignore

    def test_different_messages_not_duplicate(self):
        assert _is_duplicate("wamid.aaa") is False
        assert _is_duplicate("wamid.bbb") is False


# ---------------------------------------------------------------------------
# 3. Memory Retrieval
# ---------------------------------------------------------------------------

class TestMemoryRetrieval:
    def test_retrieves_memory_for_contact(self):
        mock_db = MagicMock()
        mock_record = MagicMock()
        mock_record.content = "[WhatsApp inbound] Hello from customer"
        mock_record.metadata_json = {"direction": "inbound"}
        mock_record.created_at = datetime.now(timezone.utc)

        from sqlalchemy import select
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_db.execute.return_value = mock_result

        context = _retrieve_contact_memory(mock_db, "whatsapp:John", "Hi there")
        assert len(context) == 1
        assert context[0]["role"] == "user"
        assert "Hello from customer" in context[0]["content"]

    def test_outbound_memory标记_as_assistant(self):
        mock_db = MagicMock()
        mock_record = MagicMock()
        mock_record.content = "[WhatsApp outbound] Sure, I can help"
        mock_record.metadata_json = {"direction": "outbound"}
        mock_record.created_at = datetime.now(timezone.utc)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_record]
        mock_db.execute.return_value = mock_result

        context = _retrieve_contact_memory(mock_db, "whatsapp:John", "Thanks")
        assert len(context) == 1
        assert context[0]["role"] == "assistant"

    def test_empty_memory_returns_empty_list(self):
        mock_db = MagicMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        context = _retrieve_contact_memory(mock_db, "whatsapp:NewUser", "Hi")
        assert context == []

    def test_memory_isolation_between_contacts(self):
        """Contact A's memory must not appear in Contact B's context."""
        mock_db = MagicMock()

        # First call: Contact A
        mock_result_a = MagicMock()
        mock_record_a = MagicMock()
        mock_record_a.content = "Secret A conversation"
        mock_record_a.metadata_json = {"direction": "inbound"}
        mock_record_a.created_at = datetime.now(timezone.utc)
        mock_result_a.scalars.return_value.all.return_value = [mock_record_a]

        # Second call: Contact B
        mock_result_b = MagicMock()
        mock_result_b.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [mock_result_a, mock_result_b]

        context_a = _retrieve_contact_memory(mock_db, "whatsapp:ContactA", "Hi")
        context_b = _retrieve_contact_memory(mock_db, "whatsapp:ContactB", "Hi")

        assert len(context_a) == 1
        assert "Secret A" in context_a[0]["content"]
        assert context_b == []

    def test_exception_returns_empty(self):
        mock_db = MagicMock()
        mock_db.execute.side_effect = Exception("DB error")
        context = _retrieve_contact_memory(mock_db, "whatsapp:John", "Hi")
        assert context == []


# ---------------------------------------------------------------------------
# 4. Response Generation
# ---------------------------------------------------------------------------

class TestResponseGeneration:
    def test_uses_llm_when_configured(self):
        with patch("app.llm.provider_factory.ProviderFactory") as mock_factory:
            with patch("app.llm.base_provider.provider_configured", return_value=True):
                mock_provider = MagicMock()
                mock_provider.request.return_value = {"response": "Hello! How can I help?"}
                mock_factory.create.return_value = mock_provider

                response = _generate_response("John", "Hi there", [], "Be helpful.")
                assert response == "Hello! How can I help?"

    def test_fallback_when_llm_not_configured(self):
        with patch("app.llm.base_provider.provider_configured", return_value=False):
            response = _generate_response("John", "Hi there", [], "Be helpful.")
            assert "team member" in response.lower()

    def test_fallback_when_llm_fails(self):
        with patch("app.llm.provider_factory.ProviderFactory") as mock_factory:
            mock_factory.create.side_effect = Exception("LLM unavailable")
            response = _generate_response("John", "Hi there", [], "Be helpful.")
            assert "team member" in response.lower()

    def test_truncates_long_response(self):
        with patch("app.llm.provider_factory.ProviderFactory") as mock_factory:
            with patch("app.llm.base_provider.provider_configured", return_value=True):
                mock_provider = MagicMock()
                mock_provider.request.return_value = {"response": "x" * 2000}
                mock_factory.create.return_value = mock_provider

                response = _generate_response("John", "Hi", [], "Prompt.")
                assert len(response) <= 1000
                assert response.endswith("...")

    def test_includes_memory_in_prompt(self):
        with patch("app.llm.provider_factory.ProviderFactory") as mock_factory:
            with patch("app.llm.base_provider.provider_configured", return_value=True):
                mock_provider = MagicMock()
                mock_provider.request.return_value = {"response": "OK"}
                mock_factory.create.return_value = mock_provider

                memory = [
                    {"role": "user", "content": "Previous question"},
                    {"role": "assistant", "content": "Previous answer"},
                ]
                _generate_response("John", "Follow-up", memory, "System prompt.")

                # Verify memory was included in the prompt
                call_args = mock_provider.request.call_args[0][0]
                assert "Previous question" in call_args
                assert "Previous answer" in call_args
                assert "Follow-up" in call_args


# ---------------------------------------------------------------------------
# 5. Inbound Message Processing
# ---------------------------------------------------------------------------

class TestInboundProcessing:
    def test_processes_inbound_message(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        event = _make_inbound_event()

        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_or_create_contact.return_value = MagicMock(
            id=1, name="Customer", external_id="+15551234567"
        )
        mock_repo.get_or_create_conversation.return_value = MagicMock(id=1)
        mock_repo.create_message.return_value = MagicMock(id=1)

        with patch("app.services.whatsapp_agent.WhatsAppRepository", return_value=mock_repo):
            with patch("app.services.whatsapp_agent._retrieve_contact_memory", return_value=[]):
                with patch("app.services.whatsapp_agent._generate_response", return_value="AI response"):
                    with patch("app.services.whatsapp_service.send_message") as mock_send:
                        mock_send.return_value = {
                            "status": "sent",
                            "external_message_id": "wamid.reply123",
                        }
                        result = handle_inbound_message(event, db=mock_db)

        assert result["processed"] is True
        assert result["auto_replied"] is True
        assert result["response_status"] == "sent"

    def test_skips_non_message_events(self):
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_DELIVERED,
            provider="meta",
            external_message_id="wamid.123",
            status="delivered",
        )
        result = handle_inbound_message(event, db=MagicMock())
        assert result["processed"] is False

    def test_duplicate_webhook_returns_early(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        event = _make_inbound_event(message_id="wamid.dup_test")

        # First call processes
        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_or_create_contact.return_value = MagicMock(id=1, name="C")
        mock_repo.get_or_create_conversation.return_value = MagicMock(id=1)
        mock_repo.create_message.return_value = MagicMock(id=1)

        with patch("app.services.whatsapp_agent.WhatsAppRepository", return_value=mock_repo):
            with patch("app.services.whatsapp_agent._retrieve_contact_memory", return_value=[]):
                with patch("app.services.whatsapp_agent._generate_response", return_value="OK"):
                    with patch("app.services.whatsapp_service.send_message") as mock_send:
                            mock_send.return_value = {"status": "sent"}
                            handle_inbound_message(event, db=mock_db)

        # Second call is duplicate
        result = handle_inbound_message(event, db=mock_db)
        assert result["processed"] is True
        assert result.get("reason") == "duplicate"

    def test_auto_reply_disabled(self):
        event = _make_inbound_event()
        result = handle_inbound_message(event, db=MagicMock())
        assert result["processed"] is True
        assert result.get("reason") == "auto_reply_disabled"

    def test_missing_sender_returns_error(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="meta",
            external_message_id="wamid.nosender",
            status="received",
            sender_number="",
            metadata={"body": "Hi"},
        )
        result = handle_inbound_message(event, db=MagicMock())
        assert "error" in result

    def test_empty_content_non_text(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="meta",
            external_message_id="wamid.empty",
            status="received",
            sender_number="+15551234567",
            metadata={"body": ""},
        )
        result = handle_inbound_message(event, db=MagicMock())
        assert result["processed"] is True
        assert result.get("reason") == "non_text_message"

    def test_send_failure_still_records_result(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        event = _make_inbound_event()

        mock_db = MagicMock()
        mock_repo = MagicMock()
        mock_repo.get_or_create_contact.return_value = MagicMock(id=1, name="C")
        mock_repo.get_or_create_conversation.return_value = MagicMock(id=1)
        mock_repo.create_message.return_value = MagicMock(id=1)

        with patch("app.services.whatsapp_agent.WhatsAppRepository", return_value=mock_repo):
            with patch("app.services.whatsapp_agent._retrieve_contact_memory", return_value=[]):
                with patch("app.services.whatsapp_agent._generate_response", return_value="Reply"):
                    with patch("app.services.whatsapp_service.send_message") as mock_send:
                            mock_send.return_value = {
                                "status": "failed",
                                "error": "Provider error",
                            }
                            result = handle_inbound_message(event, db=mock_db)

        assert result["processed"] is True
        assert result["auto_replied"] is False
        assert result.get("send_error") == "Provider error"


# ---------------------------------------------------------------------------
# 6. Agent Status
# ---------------------------------------------------------------------------

class TestAgentStatus:
    def test_status_when_disabled(self):
        status = get_agent_status()
        assert status["auto_reply_enabled"] is False
        assert "llm_configured" in status

    def test_status_when_enabled(self):
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"
        status = get_agent_status()
        assert status["auto_reply_enabled"] is True

    def test_status_includes_llm_info(self):
        with patch("app.llm.provider_factory.ProviderFactory") as mock_factory:
            with patch("app.llm.base_provider.provider_configured", return_value=True):
                mock_provider = MagicMock()
                mock_provider.__class__.__name__ = "TestProvider"
                mock_factory.create.return_value = mock_provider
                status = get_agent_status()
                assert status["llm_configured"] is True
                assert status["llm_provider"] == "TestProvider"


# ---------------------------------------------------------------------------
# 7. Policy Enforcement (via whatsapp_service)
# ---------------------------------------------------------------------------

class TestPolicyEnforcement:
    def test_send_message_still_requires_approval(self):
        """Auto-reply bypasses policy for its own sends, but manual sends still require approval."""
        from app.services.whatsapp_service import send_message
        os.environ["WHATSAPP_PROVIDER"] = "meta"
        os.environ["META_WHATSAPP_ACCESS_TOKEN"] = "token"
        os.environ["META_WHATSAPP_PHONE_NUMBER_ID"] = "123"

        result = send_message(
            destination_number="+15551234567",
            message="Manual send",
            has_approved_context=False,
        )
        assert result["status"] == "APPROVAL_REQUIRED"


# ---------------------------------------------------------------------------
# 8. Conversation Isolation
# ---------------------------------------------------------------------------

class TestConversationIsolation:
    def test_different_contacts_get_separate_memory(self):
        """Each contact's auto-reply uses only their own memory."""
        os.environ["WHATSAPP_AUTO_REPLY_ENABLED"] = "true"

        # Contact A
        event_a = _make_inbound_event(
            message_id="wamid.contactA",
            sender="+15551111111",
            content="My secret is X",
        )
        mock_db = MagicMock()
        mock_repo = MagicMock()
        contact_a = MagicMock(id=1, external_id="+15551111111")
        contact_a.name = "Alice"
        mock_repo.get_or_create_contact.return_value = contact_a
        mock_repo.get_or_create_conversation.return_value = MagicMock(id=1)
        mock_repo.create_message.return_value = MagicMock(id=1)

        with patch("app.services.whatsapp_agent.WhatsAppRepository", return_value=mock_repo):
            with patch("app.services.whatsapp_agent._retrieve_contact_memory", return_value=[]) as mock_mem:
                with patch("app.services.whatsapp_agent._generate_response", return_value="OK"):
                    with patch("app.services.whatsapp_service.send_message") as mock_send:
                            mock_send.return_value = {"status": "sent"}
                            handle_inbound_message(event_a, db=mock_db)

                # Verify memory was retrieved for correct entity
                mock_mem.assert_called_with(mock_db, "whatsapp:Alice", "My secret is X")

        # Contact B should not see Alice's memory
        event_b = _make_inbound_event(
            message_id="wamid.contactB",
            sender="+15552222222",
            content="Hello",
        )
        contact_b = MagicMock(id=2, external_id="+15552222222")
        contact_b.name = "Bob"
        mock_repo.get_or_create_contact.return_value = contact_b

        with patch("app.services.whatsapp_agent.WhatsAppRepository", return_value=mock_repo):
            with patch("app.services.whatsapp_agent._retrieve_contact_memory", return_value=[]) as mock_mem:
                with patch("app.services.whatsapp_agent._generate_response", return_value="OK"):
                    with patch("app.services.whatsapp_service.send_message") as mock_send:
                            mock_send.return_value = {"status": "sent"}
                            handle_inbound_message(event_b, db=mock_db)

                # Verify Bob's memory entity is used, not Alice's
                mock_mem.assert_called_with(mock_db, "whatsapp:Bob", "Hello")
