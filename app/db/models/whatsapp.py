"""WhatsApp data models for GoalOS.

Persistent models tracking WhatsApp contacts, conversations, and messages.
These are NOT memory records — they track the communication transport layer.
The WhatsApp service creates corresponding memory events for the GoalOS
memory system.
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
    Boolean,
)
from sqlalchemy.orm import relationship

from app.db.base import Base


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"


class MediaType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    LOCATION = "location"
    CONTACT = "contact"
    STICKER = "sticker"


class HandoffState(str, enum.Enum):
    AI_ACTIVE = "ai_active"
    HUMAN_REQUESTED = "human_requested"
    HUMAN_ACTIVE = "human_active"
    RESOLVED = "resolved"


class WhatsAppContact(Base):
    """A WhatsApp contact seen through the provider."""

    __tablename__ = "whatsapp_contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, default="openwa")
    external_id = Column(String(128), nullable=False, unique=True)
    phone_number = Column(String(32), nullable=False)
    name = Column(String(256), nullable=True)
    profile_pic_url = Column(String(1024), nullable=True)
    is_business = Column(Boolean, default=False)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    conversations = relationship(
        "WhatsAppConversation", back_populates="contact", cascade="all, delete-orphan"
    )


class WhatsAppConversation(Base):
    """A WhatsApp conversation thread."""

    __tablename__ = "whatsapp_conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, default="openwa")
    external_conversation_id = Column(String(256), nullable=True)
    contact_id = Column(Integer, ForeignKey("whatsapp_contacts.id"), nullable=False)
    direction = Column(Enum(MessageDirection), nullable=False)
    last_message_at = Column(DateTime, nullable=True)
    message_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    contact = relationship("WhatsAppContact", back_populates="conversations")
    messages = relationship(
        "WhatsAppMessage", back_populates="conversation", cascade="all, delete-orphan"
    )


class WhatsAppMessage(Base):
    """A single WhatsApp message."""

    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(32), nullable=False, default="openwa")
    external_message_id = Column(String(256), nullable=True, unique=True)
    conversation_id = Column(
        Integer, ForeignKey("whatsapp_conversations.id"), nullable=False
    )
    direction = Column(Enum(MessageDirection), nullable=False)
    media_type = Column(Enum(MediaType), nullable=False, default=MediaType.TEXT)
    content = Column(Text, nullable=True)
    media_url = Column(String(1024), nullable=True)
    caption = Column(Text, nullable=True)
    status = Column(Enum(MessageStatus), nullable=False, default=MessageStatus.PENDING)
    provider_status = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    conversation = relationship("WhatsAppConversation", back_populates="messages")


class WhatsAppHandoff(Base):
    """Tracks human handoff state for a WhatsApp conversation.

    When the AI agent detects that a conversation should be escalated
    to a human operator, a handoff record is created. The handoff
    tracks state transitions through the lifecycle.
    """

    __tablename__ = "whatsapp_handoffs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer, ForeignKey("whatsapp_conversations.id"), nullable=False, unique=True
    )
    state = Column(Enum(HandoffState), nullable=False, default=HandoffState.AI_ACTIVE)
    escalation_reason = Column(String(256), nullable=True)
    escalation_detail = Column(Text, nullable=True)
    assigned_to = Column(String(128), nullable=True)
    resolution_notes = Column(Text, nullable=True)
    requested_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    conversation = relationship("WhatsAppConversation")


class WhatsAppAnalytics(Base):
    """Per-conversation analytics record.

    Tracks message counts, response latency, AI success/failure,
    handoff events, and conversation duration. Updated on each
    significant event rather than computed on read.
    """

    __tablename__ = "whatsapp_analytics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        Integer, ForeignKey("whatsapp_conversations.id"), nullable=False, unique=True
    )
    contact_id = Column(
        Integer, ForeignKey("whatsapp_contacts.id"), nullable=False
    )
    provider = Column(String(32), nullable=False, default="meta")

    # Message counts
    total_messages = Column(Integer, default=0)
    inbound_count = Column(Integer, default=0)
    outbound_count = Column(Integer, default=0)
    ai_response_count = Column(Integer, default=0)
    failed_response_count = Column(Integer, default=0)

    # Timing
    first_message_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, nullable=True)
    avg_response_latency_ms = Column(Integer, nullable=True)
    total_response_latency_ms = Column(Integer, default=0)
    response_latency_samples = Column(Integer, default=0)

    # Handoff
    handoff_count = Column(Integer, default=0)
    handoff_reasons = Column(Text, nullable=True)  # JSON list of reasons
    last_handoff_reason = Column(String(256), nullable=True)

    # Quality
    ai_resolution_rate = Column(Integer, default=0)  # 0-100 percentage
    conversation_duration_seconds = Column(Integer, default=0)
    resolution_status = Column(String(32), nullable=True)  # resolved, unresolved, escalated
    detected_language = Column(String(16), nullable=True)

    # Metadata
    created_at = Column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    conversation = relationship("WhatsAppConversation")
    contact = relationship("WhatsAppContact")
