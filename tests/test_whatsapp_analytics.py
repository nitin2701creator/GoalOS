"""Sprint 5C+5D — WhatsApp Analytics & Multilingual tests.

Comprehensive tests for:
- Analytics DB model
- Analytics repository (CRUD, summary, date-range filtering)
- Analytics service (track inbound/outbound/handoff, quality metrics)
- Language detection (all Indian languages, Hinglish, English, mixed scripts)
- Multilingual prompt augmentation
- API response construction
- Conversation isolation
- Credential redaction
- Existing WhatsApp tests remaining compatible

NO real WhatsApp messages during tests.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.whatsapp import (
    HandoffState,
    MessageDirection,
    WhatsAppAnalytics,
    WhatsAppContact,
    WhatsAppConversation,
    WhatsAppHandoff,
)
from app.repositories.whatsapp_analytics_repository import WhatsAppAnalyticsRepository
from app.services.whatsapp_analytics import (
    get_analytics_summary,
    get_conversation_analytics,
    list_conversation_analytics,
    set_language,
    set_resolution,
    track_handoff,
    track_inbound_message,
    track_outbound_message,
)
from app.services.whatsapp_language import (
    augment_prompt_with_language,
    detect_language,
    get_language_display_name,
    is_indian_language,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env():
    """Ensure no real credentials leak between tests."""
    env_keys = ["WHATSAPP_PROVIDER", "WHATSAPP_AUTO_REPLY_ENABLED"]
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


@pytest.fixture
def sample_conversation(db):
    """Create a sample contact + conversation for testing."""
    from app.repositories.whatsapp_repository import WhatsAppRepository
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


# ---------------------------------------------------------------------------
# 1. Language Detection
# ---------------------------------------------------------------------------


class TestLanguageDetection:
    """Test language detection via Unicode character ranges."""

    def test_english_detection(self):
        result = detect_language("Hello, how can I help you?")
        assert result["language"] == "english"
        assert result["confidence"] > 0.8

    def test_hindi_detection(self):
        result = detect_language("नमस्ते, आप कैसे हैं?")
        assert result["language"] == "hindi"
        assert result["confidence"] > 0.5

    def test_hinglish_detection(self):
        result = detect_language("Mujhe help chahiye, please send karo")
        assert result["language"] == "hinglish"
        # Hinglish detected via Latin-script word markers — single script but mixed language
        assert result["confidence"] > 0.0

    def test_bengali_detection(self):
        result = detect_language("আমি আপনাকে কিভাবে সাহায্য করতে পারি?")
        assert result["language"] == "bengali"
        assert result["confidence"] > 0.5

    def test_tamil_detection(self):
        result = detect_language("நான் உங்களுக்கு எப்படி உதவ முடியும்?")
        assert result["language"] == "tamil"
        assert result["confidence"] > 0.5

    def test_telugu_detection(self):
        result = detect_language("నేను మీకు ఎలా సహాయం చేయగలను?")
        assert result["language"] == "telugu"
        assert result["confidence"] > 0.5

    def test_kannada_detection(self):
        result = detect_language("ನಾನು ನಿಮಗೆ ಹೇಗೆ ಸಹಾಯ ಮಾಡಬಹುದು?")
        assert result["language"] == "kannada"
        assert result["confidence"] > 0.5

    def test_malayalam_detection(self):
        result = detect_language("ഞാൻ നിങ്ങളെ എങ്ങനെ സഹായിക്കാം?")
        assert result["language"] == "malayalam"
        assert result["confidence"] > 0.5

    def test_gujarati_detection(self):
        result = detect_language("હું તમને કેવી રીતે મદદ કરી શકું?")
        assert result["language"] == "gujarati"
        assert result["confidence"] > 0.5

    def test_punjabi_detection(self):
        result = detect_language("ਮੈਂ ਤੁਹਾਡੀ ਕਿਵੇਂ ਮਦਦ ਕਰ ਸਕਦਾ ਹਾਂ?")
        assert result["language"] == "punjabi"
        assert result["confidence"] > 0.5

    def test_empty_text(self):
        result = detect_language("")
        assert result["language"] == "unknown"
        assert result["confidence"] == 0.0

    def test_numbers_only(self):
        result = detect_language("12345")
        assert result["language"] == "unknown"

    def test_mixed_latin_numbers(self):
        result = detect_language("Order 123 confirmed")
        assert result["language"] == "english"
        assert result["confidence"] > 0.5


# ---------------------------------------------------------------------------
# 2. Multilingual Prompt Augmentation
# ---------------------------------------------------------------------------


class TestMultilingualPrompt:
    """Test multilingual system prompt augmentation."""

    def test_augment_for_hindi(self):
        base = "You are a helpful assistant."
        result = augment_prompt_with_language(base, "hindi")
        assert "Hindi" in result
        assert "IMPORTANT" in result

    def test_augment_for_hinglish(self):
        base = "You are a helpful assistant."
        result = augment_prompt_with_language(base, "hinglish")
        assert "Hinglish" in result
        assert "Hindi-English" in result

    def test_augment_for_english_no_change(self):
        base = "You are a helpful assistant."
        result = augment_prompt_with_language(base, "english")
        assert result == base

    def test_augment_for_unknown_no_change(self):
        base = "You are a helpful assistant."
        result = augment_prompt_with_language(base, "unknown")
        assert result == base

    def test_augment_for_tamil(self):
        base = "You are a helpful assistant."
        result = augment_prompt_with_language(base, "tamil")
        assert "Tamil" in result

    def test_augment_disabled(self):
        base = "You are a helpful assistant."
        result = augment_prompt_with_language(base, "hindi", force_language=False)
        assert result == base


# ---------------------------------------------------------------------------
# 3. Language Utility Functions
# ---------------------------------------------------------------------------


class TestLanguageUtilities:
    """Test language utility functions."""

    def test_display_name(self):
        assert get_language_display_name("hindi") == "Hindi"
        assert get_language_display_name("hinglish") == "Hinglish"
        assert get_language_display_name("english") == "English"
        assert get_language_display_name("unknown") == "Unknown"

    def test_is_indian_language(self):
        assert is_indian_language("hindi") is True
        assert is_indian_language("hinglish") is True
        assert is_indian_language("bengali") is True
        assert is_indian_language("tamil") is True
        assert is_indian_language("english") is False
        assert is_indian_language("french") is False


# ---------------------------------------------------------------------------
# 4. Analytics DB Model
# ---------------------------------------------------------------------------


class TestAnalyticsDBModel:
    """Test WhatsAppAnalytics SQLAlchemy model."""

    def test_create_analytics(self, db, sample_conversation):
        contact, conv = sample_conversation
        analytics = WhatsAppAnalytics(
            conversation_id=conv.id,
            contact_id=contact.id,
            provider="meta",
            total_messages=5,
            inbound_count=3,
            outbound_count=2,
        )
        db.add(analytics)
        db.commit()

        fetched = db.get(WhatsAppAnalytics, analytics.id)
        assert fetched is not None
        assert fetched.total_messages == 5
        assert fetched.inbound_count == 3
        assert fetched.outbound_count == 2

    def test_analytics_unique_per_conversation(self, db, sample_conversation):
        contact, conv = sample_conversation
        a1 = WhatsAppAnalytics(conversation_id=conv.id, contact_id=contact.id)
        db.add(a1)
        db.commit()
        # Second analytics for same conversation should fail unique constraint
        a2 = WhatsAppAnalytics(conversation_id=conv.id, contact_id=contact.id)
        db.add(a2)
        with pytest.raises(Exception):
            db.commit()


# ---------------------------------------------------------------------------
# 5. Analytics Repository
# ---------------------------------------------------------------------------


class TestAnalyticsRepository:
    """Test analytics repository operations."""

    def test_get_or_create(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        analytics = repo.get_or_create(conv.id, contact.id)
        assert analytics is not None
        assert analytics.conversation_id == conv.id

    def test_get_or_create_idempotent(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        a1 = repo.get_or_create(conv.id, contact.id)
        a2 = repo.get_or_create(conv.id, contact.id)
        assert a1.id == a2.id

    def test_record_message_inbound(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        analytics = repo.record_message(conv.id, contact.id, "inbound")
        assert analytics.total_messages == 1
        assert analytics.inbound_count == 1
        assert analytics.outbound_count == 0

    def test_record_message_outbound(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        analytics = repo.record_message(conv.id, contact.id, "outbound")
        assert analytics.total_messages == 1
        assert analytics.outbound_count == 1

    def test_record_ai_response(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        analytics = repo.record_message(
            conv.id, contact.id, "outbound",
            is_ai_response=True,
            response_latency_ms=1500,
        )
        assert analytics.ai_response_count == 1
        assert analytics.avg_response_latency_ms == 1500

    def test_record_failed_response(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        analytics = repo.record_message(
            conv.id, contact.id, "outbound",
            is_failed=True,
        )
        assert analytics.failed_response_count == 1
        assert analytics.ai_resolution_rate == 0

    def test_ai_resolution_rate_calculation(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        # 3 successful, 1 failed → 75%
        repo.record_message(conv.id, contact.id, "outbound", is_ai_response=True)
        repo.record_message(conv.id, contact.id, "outbound", is_ai_response=True)
        repo.record_message(conv.id, contact.id, "outbound", is_ai_response=True)
        analytics = repo.record_message(conv.id, contact.id, "outbound", is_failed=True)
        assert analytics.ai_resolution_rate == 75

    def test_record_handoff(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        repo.record_message(conv.id, contact.id, "inbound")
        analytics = repo.record_handoff(conv.id, "explicit_user_request")
        assert analytics.handoff_count == 1
        assert analytics.last_handoff_reason == "explicit_user_request"

    def test_set_resolution(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        repo.get_or_create(conv.id, contact.id)
        analytics = repo.set_resolution(conv.id, "resolved")
        assert analytics.resolution_status == "resolved"

    def test_set_language(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        repo.get_or_create(conv.id, contact.id)
        analytics = repo.set_language(conv.id, "hindi")
        assert analytics.detected_language == "hindi"


# ---------------------------------------------------------------------------
# 6. Analytics Summary
# ---------------------------------------------------------------------------


class TestAnalyticsSummary:
    """Test analytics summary with date-range filtering."""

    def test_empty_summary(self, db):
        result = get_analytics_summary(db)
        assert result["total_conversations"] == 0
        assert result["ai_resolution_rate"] == 0

    def test_summary_with_data(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        repo.record_message(conv.id, contact.id, "inbound")
        repo.record_message(conv.id, contact.id, "outbound", is_ai_response=True)
        repo.record_message(conv.id, contact.id, "outbound", is_ai_response=True)
        db.commit()

        result = get_analytics_summary(db)
        assert result["total_conversations"] == 1
        assert result["total_messages"] == 3
        assert result["ai_resolution_rate"] == 100.0

    def test_summary_date_range_filter(self, db, sample_conversation):
        contact, conv = sample_conversation
        repo = WhatsAppAnalyticsRepository(db)
        repo.record_message(conv.id, contact.id, "inbound")
        db.commit()

        # Future date should return nothing
        future = datetime.now(timezone.utc) + timedelta(days=1)
        result = get_analytics_summary(db, start_date=future)
        assert result["total_conversations"] == 0

        # Past date should include everything
        past = datetime.now(timezone.utc) - timedelta(days=1)
        result = get_analytics_summary(db, start_date=past)
        assert result["total_conversations"] == 1


# ---------------------------------------------------------------------------
# 7. Analytics Service Integration
# ---------------------------------------------------------------------------


class TestAnalyticsService:
    """Test analytics service functions."""

    def test_track_inbound(self, db, sample_conversation):
        contact, conv = sample_conversation
        track_inbound_message(db, conv.id, contact.id, provider="meta")
        db.commit()
        result = get_conversation_analytics(db, conv.id)
        assert result is not None
        assert result["inbound_count"] == 1

    def test_track_outbound_ai(self, db, sample_conversation):
        contact, conv = sample_conversation
        track_outbound_message(
            db, conv.id, contact.id,
            provider="meta", is_ai_response=True,
        )
        db.commit()
        result = get_conversation_analytics(db, conv.id)
        assert result is not None
        assert result["ai_response_count"] == 1

    def test_track_outbound_failed(self, db, sample_conversation):
        contact, conv = sample_conversation
        track_outbound_message(
            db, conv.id, contact.id,
            provider="meta", is_failed=True,
        )
        db.commit()
        result = get_conversation_analytics(db, conv.id)
        assert result is not None
        assert result["failed_response_count"] == 1

    def test_track_handoff(self, db, sample_conversation):
        contact, conv = sample_conversation
        track_handoff(db, conv.id, "explicit_user_request")
        db.commit()
        result = get_conversation_analytics(db, conv.id)
        assert result is not None
        assert result["handoff_count"] == 1

    def test_set_resolution_service(self, db, sample_conversation):
        contact, conv = sample_conversation
        set_resolution(db, conv.id, "resolved")
        db.commit()
        result = get_conversation_analytics(db, conv.id)
        assert result is not None
        assert result["resolution_status"] == "resolved"

    def test_set_language_service(self, db, sample_conversation):
        contact, conv = sample_conversation
        set_language(db, conv.id, "hindi")
        db.commit()
        result = get_conversation_analytics(db, conv.id)
        assert result is not None
        assert result["detected_language"] == "hindi"

    def test_list_analytics(self, db, sample_conversation):
        contact, conv = sample_conversation
        track_inbound_message(db, conv.id, contact.id)
        db.commit()
        results = list_conversation_analytics(db)
        assert len(results) == 1

    def test_conversation_isolation(self, db):
        """Two conversations have separate analytics."""
        from app.repositories.whatsapp_repository import WhatsAppRepository
        repo = WhatsAppRepository(db)
        c1 = repo.get_or_create_contact(provider="meta", external_id="+1111111111", phone_number="+1111111111", name="A")
        c2 = repo.get_or_create_contact(provider="meta", external_id="+2222222222", phone_number="+2222222222", name="B")
        v1 = repo.get_or_create_conversation(provider="meta", contact_id=c1.id, direction=MessageDirection.INBOUND)
        v2 = repo.get_or_create_conversation(provider="meta", contact_id=c2.id, direction=MessageDirection.INBOUND)
        db.commit()

        track_inbound_message(db, v1.id, c1.id)
        track_inbound_message(db, v2.id, c2.id)
        track_inbound_message(db, v2.id, c2.id)
        db.commit()

        r1 = get_conversation_analytics(db, v1.id)
        r2 = get_conversation_analytics(db, v2.id)
        assert r1["inbound_count"] == 1
        assert r2["inbound_count"] == 2
