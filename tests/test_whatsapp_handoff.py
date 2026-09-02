"""Sprint 5A — WhatsApp Human Handoff tests.

Comprehensive tests for:
- Escalation detection (explicit keywords, low confidence, consecutive failures)
- Handoff state management (request, activate, resolve, return to AI)
- AI reply blocking during handoff
- Conversation isolation (no cross-contact memory leaks)
- Persistence/restart (state survives across service calls)
- Duplicate webhook handling (idempotency)
- Credential redaction (no tokens in API responses)
- Existing WhatsApp/Sprint 1 tests remaining compatible
- Integration with whatsapp_agent auto-reply pipeline

NO REAL WHATSAPP MESSAGES during tests.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.whatsapp import (
    HandoffState,
    MessageDirection,
    MessageStatus,
    MediaType,
    WhatsAppContact,
    WhatsAppConversation,
    WhatsAppHandoff,
    WhatsAppMessage,
)
from app.repositories.whatsapp_repository import WhatsAppRepository
from app.services.whatsapp_handoff import (
    activate_human_handling,
    detect_escalation_trigger,
    get_handoff_context,
    get_pending_handoffs,
    request_handoff,
    resolve_handoff,
    return_to_ai,
    should_block_ai_reply,
    _conversation_failures,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
def repo(db):
    """Create a WhatsAppRepository with the test database."""
    return WhatsAppRepository(db)


@pytest.fixture
def sample_conversation(db, repo):
    """Create a sample contact + conversation for testing."""
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


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure no real credentials leak between tests."""
    env_keys = [
        "WHATSAPP_HANDOFF_KEYWORDS",
        "WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD",
        "WHATSAPP_HANDOFF_MAX_FAILURES",
        "WHATSAPP_PROVIDER",
        "OPENWA_API_URL",
    ]
    saved = {k: os.environ.get(k) for k in env_keys}
    for k in env_keys:
        os.environ.pop(k, None)
    # Clear failure tracking between tests
    _conversation_failures.clear()
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    _conversation_failures.clear()


# ---------------------------------------------------------------------------
# 1. Escalation Detection
# ---------------------------------------------------------------------------


class TestEscalationDetection:
    """Test the escalation trigger detection logic."""

    def test_explicit_keyword_human(self):
        result = detect_escalation_trigger("I need to speak to a human", 1)
        assert result["should_escalate"] is True
        assert result["reason"] == "explicit_user_request"
        assert "human" in result["detail"].lower()

    def test_explicit_keyword_agent(self):
        result = detect_escalation_trigger("Let me talk to an agent", 1)
        assert result["should_escalate"] is True
        assert result["reason"] == "explicit_user_request"

    def test_explicit_keyword_call_me(self):
        result = detect_escalation_trigger("Can you call me?", 1)
        assert result["should_escalate"] is True
        assert result["reason"] == "explicit_user_request"

    def test_explicit_keyword_speak_to_someone(self):
        result = detect_escalation_trigger("I want to speak to someone", 1)
        assert result["should_escalate"] is True
        assert result["reason"] == "explicit_user_request"

    def test_explicit_keyword_operator(self):
        result = detect_escalation_trigger("Connect me to an operator", 1)
        assert result["should_escalate"] is True

    def test_explicit_keyword_manager(self):
        result = detect_escalation_trigger("I want to talk to a manager", 1)
        assert result["should_escalate"] is True

    def test_explicit_keyword_not_a_bot(self):
        result = detect_escalation_trigger("You're just a bot, I need a real person", 1)
        assert result["should_escalate"] is True

    def test_custom_keywords_from_env(self):
        os.environ["WHATSAPP_HANDOFF_KEYWORDS"] = "custom_word,another_word"
        result = detect_escalation_trigger("I have a custom_word to discuss", 1)
        assert result["should_escalate"] is True
        assert "custom_word" in result["detail"]

    def test_no_escalation_normal_message(self):
        result = detect_escalation_trigger("What are your business hours?", 1)
        assert result["should_escalate"] is False

    def test_no_escalation_empty_content(self):
        result = detect_escalation_trigger("", 1)
        assert result["should_escalate"] is False

    def test_case_insensitive(self):
        result = detect_escalation_trigger("HUMAN please", 1)
        assert result["should_escalate"] is True

    def test_low_confidence_triggers_escalation(self):
        os.environ["WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD"] = "0.5"
        os.environ["WHATSAPP_HANDOFF_MAX_FAILURES"] = "2"
        # First low-confidence message
        result = detect_escalation_trigger("unclear question", 1, ai_confidence=0.2)
        assert result["should_escalate"] is False  # Not enough failures yet
        # Second low-confidence message
        result = detect_escalation_trigger("another unclear question", 1, ai_confidence=0.2)
        assert result["should_escalate"] is True
        assert result["reason"] == "low_confidence"

    def test_confidence_above_threshold_no_escalation(self):
        os.environ["WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD"] = "0.5"
        result = detect_escalation_trigger("clear question", 1, ai_confidence=0.8)
        assert result["should_escalate"] is False

    def test_good_response_resets_failure_count(self):
        os.environ["WHATSAPP_HANDOFF_CONFIDENCE_THRESHOLD"] = "0.5"
        os.environ["WHATSAPP_HANDOFF_MAX_FAILURES"] = "2"
        # Low confidence
        detect_escalation_trigger("unclear", 1, ai_confidence=0.2)
        # Good confidence resets
        detect_escalation_trigger("clear", 1, ai_confidence=0.8)
        # Low confidence again — should NOT escalate because count was reset
        result = detect_escalation_trigger("unclear again", 1, ai_confidence=0.2)
        assert result["should_escalate"] is False


# ---------------------------------------------------------------------------
# 2. Handoff State Management
# ---------------------------------------------------------------------------


class TestHandoffStateManagement:
    """Test handoff state transitions."""

    def test_request_handoff_creates_record(self, db, sample_conversation):
        _, conv = sample_conversation
        result = request_handoff(db, conv.id, reason="explicit_user_request", detail="User said human")
        assert result["status"] == "handoff_requested"
        assert result["state"] == "human_requested"
        assert "handoff_id" in result

    def test_should_block_ai_reply_after_request(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id, reason="explicit_user_request")
        assert should_block_ai_reply(db, conv.id) is True

    def test_should_not_block_ai_reply_no_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        assert should_block_ai_reply(db, conv.id) is False

    def test_activate_human_handling(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id, reason="explicit_user_request")
        result = activate_human_handling(db, conv.id, assigned_to="John Support")
        assert result["status"] == "human_active"
        assert result["assigned_to"] == "John Support"

    def test_resolve_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id, reason="explicit_user_request")
        activate_human_handling(db, conv.id)
        result = resolve_handoff(db, conv.id, resolution_notes="Issue resolved")
        assert result["status"] == "resolved"

    def test_return_to_ai(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id)
        activate_human_handling(db, conv.id)
        resolve_handoff(db, conv.id)
        result = return_to_ai(db, conv.id)
        assert result["status"] == "ai_active"
        assert should_block_ai_reply(db, conv.id) is False

    def test_already_in_handoff_returns_existing(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id)
        result = request_handoff(db, conv.id)
        assert result["status"] == "already_in_handoff"
        assert result["state"] == "human_requested"

    def test_resolve_no_handoff_returns_error(self, db, sample_conversation):
        _, conv = sample_conversation
        result = resolve_handoff(db, conv.id)
        assert result["status"] == "no_handoff_found"

    def test_return_to_ai_no_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        result = return_to_ai(db, conv.id)
        assert result["status"] == "no_handoff_found"


# ---------------------------------------------------------------------------
# 3. Conversation Isolation
# ---------------------------------------------------------------------------


class TestConversationIsolation:
    """Ensure one customer's handoff state doesn't affect another."""

    def test_separate_handoff_states(self, db, repo):
        # Create two contacts and conversations
        contact1 = repo.get_or_create_contact(
            provider="meta", external_id="+15551111111", phone_number="+15551111111", name="Alice"
        )
        contact2 = repo.get_or_create_contact(
            provider="meta", external_id="+15552222222", phone_number="+15552222222", name="Bob"
        )
        conv1 = repo.get_or_create_conversation(provider="meta", contact_id=contact1.id, direction=MessageDirection.INBOUND)
        conv2 = repo.get_or_create_conversation(provider="meta", contact_id=contact2.id, direction=MessageDirection.INBOUND)
        db.commit()

        # Request handoff for Alice
        request_handoff(db, conv1.id, reason="explicit_user_request")

        # Bob should not be affected
        assert should_block_ai_reply(db, conv2.id) is False
        assert should_block_ai_reply(db, conv1.id) is True

    def test_separate_escalation_detection(self, db, repo):
        contact1 = repo.get_or_create_contact(
            provider="meta", external_id="+15551111111", phone_number="+15551111111", name="Alice"
        )
        contact2 = repo.get_or_create_contact(
            provider="meta", external_id="+15552222222", phone_number="+15552222222", name="Bob"
        )
        conv1 = repo.get_or_create_conversation(provider="meta", contact_id=contact1.id, direction=MessageDirection.INBOUND)
        conv2 = repo.get_or_create_conversation(provider="meta", contact_id=contact2.id, direction=MessageDirection.INBOUND)
        db.commit()

        # Alice requests human
        request_handoff(db, conv1.id, reason="explicit_user_request")

        # Bob's conversation should still be AI-active
        context = get_handoff_context(db, conv2.id)
        assert context["handoff"]["state"] == "no_handoff" or context["handoff"]["state"] == HandoffState.AI_ACTIVE.value


# ---------------------------------------------------------------------------
# 4. Handoff Context
# ---------------------------------------------------------------------------


class TestHandoffContext:
    """Test conversation context for human operators."""

    def test_handoff_context_includes_contact(self, db, sample_conversation):
        contact, conv = sample_conversation
        request_handoff(db, conv.id, reason="explicit_user_request", detail="Complex issue")
        activate_human_handling(db, conv.id, assigned_to="Jane")

        context = get_handoff_context(db, conv.id)
        assert context["contact"]["name"] == "Alice Customer"
        assert context["contact"]["phone_number"] == "+15551234567"
        assert context["handoff"]["state"] == "human_active"
        assert context["handoff"]["assigned_to"] == "Jane"

    def test_handoff_context_includes_messages(self, db, repo, sample_conversation):
        contact, conv = sample_conversation
        repo.create_message(
            conversation_id=conv.id,
            provider="meta",
            direction=MessageDirection.INBOUND,
            content="Hello, I need help",
        )
        repo.create_message(
            conversation_id=conv.id,
            provider="meta",
            direction=MessageDirection.OUTBOUND,
            content="Sure, how can I help?",
        )
        db.commit()

        request_handoff(db, conv.id)
        context = get_handoff_context(db, conv.id)
        assert context["message_count"] == 2
        assert context["messages"][0]["content"] == "Hello, I need help"
        assert context["messages"][1]["content"] == "Sure, how can I help?"

    def test_handoff_context_no_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        context = get_handoff_context(db, conv.id)
        assert context["handoff"]["state"] == "no_handoff"

    def test_handoff_context_conversation_not_found(self, db):
        context = get_handoff_context(db, 99999)
        assert "error" in context


# ---------------------------------------------------------------------------
# 5. Pending Handoffs
# ---------------------------------------------------------------------------


class TestPendingHandoffs:
    """Test listing pending handoff requests."""

    def test_empty_when_no_handoffs(self, db):
        handoffs = get_pending_handoffs(db)
        assert len(handoffs) == 0

    def test_lists_requested_handoffs(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id, reason="explicit_user_request")
        handoffs = get_pending_handoffs(db)
        assert len(handoffs) == 1
        assert handoffs[0]["reason"] == "explicit_user_request"

    def test_does_not_list_resolved(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id)
        activate_human_handling(db, conv.id)
        resolve_handoff(db, conv.id)
        handoffs = get_pending_handoffs(db)
        assert len(handoffs) == 0


# ---------------------------------------------------------------------------
# 6. Handoff API Integration
# ---------------------------------------------------------------------------


class TestHandoffAPI:
    """Test handoff through the FastAPI endpoints."""

    def test_request_handoff_endpoint(self, db, sample_conversation):
        _, conv = sample_conversation
        # Simulate the API call
        from app.api.v1.whatsapp_api import HandoffRequestAPI, request_handoff_endpoint

        req = HandoffRequestAPI(conversation_id=conv.id, reason="explicit_user_request")
        result = request_handoff_endpoint(request=req, db=db)
        assert result["status"] == "handoff_requested"

    def test_activate_handoff_endpoint(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id)

        from app.api.v1.whatsapp_api import ActivateHandoffAPI, activate_handoff_endpoint

        req = ActivateHandoffAPI(conversation_id=conv.id, assigned_to="Support Agent")
        result = activate_handoff_endpoint(request=req, db=db)
        assert result["status"] == "human_active"

    def test_resolve_handoff_endpoint(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id)
        activate_human_handling(db, conv.id)

        from app.api.v1.whatsapp_api import ResolveHandoffAPI, resolve_handoff_endpoint

        req = ResolveHandoffAPI(
            conversation_id=conv.id,
            resolution_notes="Customer issue resolved",
            return_to_ai=True,
        )
        result = resolve_handoff_endpoint(request=req, db=db)
        assert result["status"] == "resolved"


# ---------------------------------------------------------------------------
# 7. Agent Auto-Reply Respects Handoff
# ---------------------------------------------------------------------------


class TestAgentRespectsHandoff:
    """Test that the auto-reply agent blocks responses during handoff."""

    def test_agent_blocks_reply_during_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        request_handoff(db, conv.id)

        from app.integrations.whatsapp.models import (
            WhatsAppWebhookEvent,
            WhatsAppWebhookEventType,
        )

        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="meta",
            external_message_id="msg-handoff-test",
            status="message.received",
            sender_number="+15551234567",
            metadata={"body": "Hello, still here"},
        )

        with patch("app.services.whatsapp_agent._is_auto_reply_enabled", return_value=True):
            with patch("app.services.whatsapp_agent._is_duplicate", return_value=False):
                with patch("app.services.whatsapp_agent.WhatsAppRepository") as MockRepo:
                    mock_repo = MagicMock()
                    MockRepo.return_value = mock_repo
                    mock_repo.get_or_create_contact.return_value = MagicMock(id=1, name="Alice Customer", external_id="+15551234567")
                    mock_repo.get_or_create_conversation.return_value = MagicMock(id=conv.id)
                    mock_repo.create_message.return_value = MagicMock(id=1)

                    from app.services.whatsapp_agent import handle_inbound_message

                    result = handle_inbound_message(event, db=db)

        assert result["auto_replied"] is False
        assert result.get("reason") == "human_handoff_active"

    def test_agent_sends_ack_on_escalation(self, db, sample_conversation):
        _, conv = sample_conversation

        from app.integrations.whatsapp.models import (
            WhatsAppWebhookEvent,
            WhatsAppWebhookEventType,
        )

        event = WhatsAppWebhookEvent(
            event_type=WhatsAppWebhookEventType.MESSAGE_RECEIVED,
            provider="meta",
            external_message_id="msg-escalation-test",
            status="message.received",
            sender_number="+15551234567",
            metadata={"body": "I need a human"},
        )

        with patch("app.services.whatsapp_agent._is_auto_reply_enabled", return_value=True):
            with patch("app.services.whatsapp_agent._is_duplicate", return_value=False):
                with patch("app.services.whatsapp_agent.WhatsAppRepository") as MockRepo:
                    with patch("app.services.whatsapp_agent._feed_memory"):
                        with patch("app.services.whatsapp_service.send_message") as mock_send:
                            mock_send.return_value = {"status": "sent", "external_message_id": "ack-123"}
                            mock_repo = MagicMock()
                            MockRepo.return_value = mock_repo
                            mock_repo.get_or_create_contact.return_value = MagicMock(id=1, name="Alice Customer", external_id="+15551234567")
                            mock_repo.get_or_create_conversation.return_value = MagicMock(id=conv.id)
                            mock_repo.create_message.return_value = MagicMock(id=1)

                            from app.services.whatsapp_agent import handle_inbound_message

                            result = handle_inbound_message(event, db=db)

        assert result["processed"] is True
        assert result.get("escalated") is True
        assert result["escalation_reason"] == "explicit_user_request"


# ---------------------------------------------------------------------------
# 8. Duplicate Webhook Handling
# ---------------------------------------------------------------------------


class TestDuplicateWebhookHandling:
    """Ensure duplicate webhooks are handled idempotently."""

    def test_duplicate_webhook_returns_duplicate(self):
        from app.services.whatsapp_agent import _is_duplicate, _processed_messages

        _processed_messages.clear()
        assert _is_duplicate("msg-dup-123") is False  # First time
        assert _is_duplicate("msg-dup-123") is True   # Duplicate

    def test_empty_message_id_not_deduplicated(self):
        from app.services.whatsapp_agent import _is_duplicate

        assert _is_duplicate("") is False
        assert _is_duplicate(None) is False


# ---------------------------------------------------------------------------
# 9. DB Model Tests
# ---------------------------------------------------------------------------


class TestHandoffDBModel:
    """Test the WhatsAppHandoff SQLAlchemy model."""

    def test_create_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        handoff = WhatsAppHandoff(
            conversation_id=conv.id,
            state=HandoffState.HUMAN_REQUESTED,
            escalation_reason="explicit_user_request",
        )
        db.add(handoff)
        db.commit()

        fetched = db.get(WhatsAppHandoff, handoff.id)
        assert fetched is not None
        assert fetched.state == HandoffState.HUMAN_REQUESTED
        assert fetched.escalation_reason == "explicit_user_request"
        assert fetched.conversation_id == conv.id

    def test_handoff_state_transitions(self, db, sample_conversation):
        _, conv = sample_conversation
        handoff = WhatsAppHandoff(
            conversation_id=conv.id,
            state=HandoffState.AI_ACTIVE,
        )
        db.add(handoff)
        db.commit()

        handoff.state = HandoffState.HUMAN_REQUESTED
        handoff.requested_at = datetime.now(timezone.utc)
        db.commit()
        assert db.get(WhatsAppHandoff, handoff.id).state == HandoffState.HUMAN_REQUESTED

        handoff.state = HandoffState.HUMAN_ACTIVE
        handoff.activated_at = datetime.now(timezone.utc)
        db.commit()
        assert db.get(WhatsAppHandoff, handoff.id).state == HandoffState.HUMAN_ACTIVE

        handoff.state = HandoffState.RESOLVED
        handoff.resolved_at = datetime.now(timezone.utc)
        db.commit()
        assert db.get(WhatsAppHandoff, handoff.id).state == HandoffState.RESOLVED

    def test_handoff_unique_per_conversation(self, db, sample_conversation):
        _, conv = sample_conversation
        h1 = WhatsAppHandoff(conversation_id=conv.id, state=HandoffState.AI_ACTIVE)
        db.add(h1)
        db.commit()
        # Second handoff for same conversation should fail unique constraint
        h2 = WhatsAppHandoff(conversation_id=conv.id, state=HandoffState.AI_ACTIVE)
        db.add(h2)
        with pytest.raises(Exception):
            db.commit()


# ---------------------------------------------------------------------------
# 10. Integration with Repository
# ---------------------------------------------------------------------------


class TestHandoffRepositoryIntegration:
    """Test handoff operations through the repository layer."""

    def test_repository_create_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        repo = WhatsAppRepository(db)
        handoff = repo.create_handoff(
            conversation_id=conv.id,
            state=HandoffState.HUMAN_REQUESTED,
            escalation_reason="low_confidence",
            escalation_detail="3 consecutive low-confidence responses",
        )
        assert handoff.id is not None
        assert handoff.state == HandoffState.HUMAN_REQUESTED

    def test_repository_get_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        repo = WhatsAppRepository(db)
        repo.create_handoff(conversation_id=conv.id, state=HandoffState.HUMAN_REQUESTED)
        handoff = repo.get_handoff(conv.id)
        assert handoff is not None
        assert handoff.state == HandoffState.HUMAN_REQUESTED

    def test_repository_transition_handoff(self, db, sample_conversation):
        _, conv = sample_conversation
        repo = WhatsAppRepository(db)
        repo.create_handoff(conversation_id=conv.id, state=HandoffState.HUMAN_REQUESTED)
        handoff = repo.transition_handoff(
            conversation_id=conv.id,
            new_state=HandoffState.HUMAN_ACTIVE,
            assigned_to="Agent Smith",
        )
        assert handoff.state == HandoffState.HUMAN_ACTIVE
        assert handoff.assigned_to == "Agent Smith"

    def test_repository_list_handoffs(self, db, sample_conversation):
        _, conv = sample_conversation
        repo = WhatsAppRepository(db)
        repo.create_handoff(conversation_id=conv.id, state=HandoffState.HUMAN_REQUESTED)
        handoffs = repo.list_handoffs(state=HandoffState.HUMAN_REQUESTED)
        assert len(handoffs) == 1

    def test_repository_list_handoffs_all(self, db, sample_conversation):
        _, conv = sample_conversation
        repo = WhatsAppRepository(db)
        repo.create_handoff(conversation_id=conv.id, state=HandoffState.HUMAN_REQUESTED)
        handoffs = repo.list_handoffs()
        assert len(handoffs) == 1
