"""Voice call data models for GoalOS.

Persistent models tracking voice call lifecycle, outcomes, and metadata.
These support the voice analytics pipeline without storing raw audio.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    Float,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class CallDirection(str, enum.Enum):
    OUTBOUND = "outbound"
    INBOUND = "inbound"


class VoiceCallStatus(str, enum.Enum):
    QUEUED = "queued"
    INITIATED = "initiated"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    CANCELED = "canceled"


class VoiceCallRecord(Base):
    """A single voice call record."""

    __tablename__ = "voice_calls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False)
    external_call_id = Column(String(256), nullable=True, unique=True)
    direction = Column(Enum(CallDirection), nullable=False, default=CallDirection.OUTBOUND)

    # Parties
    destination_number = Column(String(32), nullable=False)
    caller_number = Column(String(32), nullable=True)

    # Status
    status = Column(Enum(VoiceCallStatus), nullable=False, default=VoiceCallStatus.QUEUED)
    provider_status = Column(String(64), nullable=True)

    # Content
    tts_message = Column(Text, nullable=True)  # What was said via TTS
    language = Column(String(16), nullable=True)

    # Timing
    initiated_at = Column(DateTime, nullable=True)
    answered_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    ring_duration_seconds = Column(Integer, nullable=True)

    # Cost
    cost = Column(Float, nullable=True)
    cost_currency = Column(String(8), nullable=True)

    # Context
    conversation_id = Column(String(256), nullable=True)  # GoalOS conversation reference
    campaign_id = Column(String(256), nullable=True)
    reference_id = Column(String(256), nullable=True)

    # Memory integration
    memory_created = Column(Integer, default=0)  # 0=no, 1=yes

    # Error
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class VoiceCallEvent(Base):
    """Webhook/status events for a voice call."""

    __tablename__ = "voice_call_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(
        Integer, ForeignKey("voice_calls.id"), nullable=False
    )
    event_type = Column(String(64), nullable=False)  # call.initiated, call.ringing, etc.
    provider = Column(String(32), nullable=False)
    status = Column(String(64), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    raw_payload = Column(Text, nullable=True)  # JSON-serialized webhook payload
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    call = relationship("VoiceCallRecord")
