"""WhatsApp repository for GoalOS.

Provides DB persistence for WhatsApp contacts, conversations, and messages.
Follows the existing GoalOS repository pattern (per-request SQLAlchemy sessions).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

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


class WhatsAppRepository:
    """DB persistence for WhatsApp data."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Contacts
    # ------------------------------------------------------------------

    def get_or_create_contact(
        self,
        provider: str,
        external_id: str,
        phone_number: str,
        name: str | None = None,
    ) -> WhatsAppContact:
        """Get an existing contact or create a new one."""
        stmt = select(WhatsAppContact).where(
            WhatsAppContact.provider == provider,
            WhatsAppContact.external_id == external_id,
        )
        contact = self.db.execute(stmt).scalar_one_or_none()
        if contact is None:
            contact = WhatsAppContact(
                provider=provider,
                external_id=external_id,
                phone_number=phone_number,
                name=name,
            )
            self.db.add(contact)
            self.db.flush()
        elif name and contact.name != name:
            contact.name = name
            contact.updated_at = datetime.now(timezone.utc)
            self.db.flush()
        return contact

    def update_contact_last_seen(
        self, contact_id: int, timestamp: datetime | None = None
    ) -> None:
        """Update the last_seen_at timestamp for a contact."""
        contact = self.db.get(WhatsAppContact, contact_id)
        if contact:
            contact.last_seen_at = timestamp or datetime.now(timezone.utc)
            contact.updated_at = datetime.now(timezone.utc)
            self.db.flush()

    def list_contacts(
        self, provider: str | None = None, limit: int = 50
    ) -> list[WhatsAppContact]:
        """List WhatsApp contacts."""
        stmt = select(WhatsAppContact)
        if provider:
            stmt = stmt.where(WhatsAppContact.provider == provider)
        stmt = stmt.order_by(WhatsAppContact.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    # ------------------------------------------------------------------
    # Conversations
    # ------------------------------------------------------------------

    def get_or_create_conversation(
        self,
        provider: str,
        contact_id: int,
        direction: MessageDirection,
        external_conversation_id: str | None = None,
    ) -> WhatsAppConversation:
        """Get an active conversation or create a new one."""
        stmt = (
            select(WhatsAppConversation)
            .where(
                WhatsAppConversation.contact_id == contact_id,
                WhatsAppConversation.is_active.is_(True),
            )
            .order_by(WhatsAppConversation.created_at.desc())
            .limit(1)
        )
        conv = self.db.execute(stmt).scalar_one_or_none()
        if conv is None:
            conv = WhatsAppConversation(
                provider=provider,
                contact_id=contact_id,
                direction=direction,
                external_conversation_id=external_conversation_id,
            )
            self.db.add(conv)
            self.db.flush()
        return conv

    def get_conversation(self, conversation_id: int) -> WhatsAppConversation | None:
        return self.db.get(WhatsAppConversation, conversation_id)

    def list_conversations(
        self, contact_id: int | None = None, active_only: bool = True, limit: int = 50
    ) -> list[WhatsAppConversation]:
        """List conversations."""
        stmt = select(WhatsAppConversation)
        if contact_id:
            stmt = stmt.where(WhatsAppConversation.contact_id == contact_id)
        if active_only:
            stmt = stmt.where(WhatsAppConversation.is_active.is_(True))
        stmt = stmt.order_by(WhatsAppConversation.last_message_at.desc().nullslast()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())

    def close_conversation(self, conversation_id: int) -> None:
        conv = self.db.get(WhatsAppConversation, conversation_id)
        if conv:
            conv.is_active = False
            conv.updated_at = datetime.now(timezone.utc)
            self.db.flush()

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def create_message(
        self,
        conversation_id: int,
        provider: str,
        direction: MessageDirection,
        content: str | None = None,
        media_type: MediaType = MediaType.TEXT,
        media_url: str | None = None,
        caption: str | None = None,
        external_message_id: str | None = None,
        status: MessageStatus = MessageStatus.PENDING,
    ) -> WhatsAppMessage:
        """Create a new message record."""
        msg = WhatsAppMessage(
            conversation_id=conversation_id,
            provider=provider,
            direction=direction,
            media_type=media_type,
            content=content,
            media_url=media_url,
            caption=caption,
            external_message_id=external_message_id,
            status=status,
        )
        self.db.add(msg)
        # Update conversation stats
        conv = self.db.get(WhatsAppConversation, conversation_id)
        if conv:
            conv.message_count = (conv.message_count or 0) + 1
            conv.last_message_at = datetime.now(timezone.utc)
        self.db.flush()
        return msg

    def update_message_status(
        self,
        external_message_id: str,
        status: MessageStatus,
        provider_status: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> WhatsAppMessage | None:
        """Update a message's delivery status."""
        stmt = select(WhatsAppMessage).where(
            WhatsAppMessage.external_message_id == external_message_id
        )
        msg = self.db.execute(stmt).scalar_one_or_none()
        if msg is None:
            return None
        msg.status = status
        msg.provider_status = provider_status
        msg.error_code = error_code
        msg.error_message = error_message
        now = datetime.now(timezone.utc)
        if status == MessageStatus.SENT:
            msg.sent_at = now
        elif status == MessageStatus.DELIVERED:
            msg.delivered_at = now
        elif status == MessageStatus.READ:
            msg.read_at = now
        self.db.flush()
        return msg

    def get_message(self, external_message_id: str) -> WhatsAppMessage | None:
        stmt = select(WhatsAppMessage).where(
            WhatsAppMessage.external_message_id == external_message_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_messages(
        self, conversation_id: int, limit: int = 50
    ) -> list[WhatsAppMessage]:
        """List messages in a conversation."""
        stmt = (
            select(WhatsAppMessage)
            .where(WhatsAppMessage.conversation_id == conversation_id)
            .order_by(WhatsAppMessage.created_at.asc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())

    def message_count(self) -> int:
        """Total message count."""
        return self.db.execute(select(func.count(WhatsAppMessage.id))).scalar_one() or 0

    # ------------------------------------------------------------------
    # Handoffs
    # ------------------------------------------------------------------

    def get_handoff(self, conversation_id: int) -> WhatsAppHandoff | None:
        """Get the handoff record for a conversation."""
        stmt = select(WhatsAppHandoff).where(
            WhatsAppHandoff.conversation_id == conversation_id
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def create_handoff(
        self,
        conversation_id: int,
        state: HandoffState = HandoffState.AI_ACTIVE,
        escalation_reason: str | None = None,
        escalation_detail: str | None = None,
    ) -> WhatsAppHandoff:
        """Create or update a handoff record for a conversation."""
        existing = self.get_handoff(conversation_id)
        now = datetime.now(timezone.utc)
        if existing:
            existing.state = state
            if escalation_reason:
                existing.escalation_reason = escalation_reason
            if escalation_detail:
                existing.escalation_detail = escalation_detail
            if state == HandoffState.HUMAN_REQUESTED:
                existing.requested_at = now
            elif state == HandoffState.HUMAN_ACTIVE:
                existing.activated_at = now
            elif state == HandoffState.RESOLVED:
                existing.resolved_at = now
            existing.updated_at = now
            self.db.flush()
            return existing

        handoff = WhatsAppHandoff(
            conversation_id=conversation_id,
            state=state,
            escalation_reason=escalation_reason,
            escalation_detail=escalation_detail,
        )
        if state == HandoffState.HUMAN_REQUESTED:
            handoff.requested_at = now
        elif state == HandoffState.HUMAN_ACTIVE:
            handoff.activated_at = now
        elif state == HandoffState.RESOLVED:
            handoff.resolved_at = now
        self.db.add(handoff)
        self.db.flush()
        return handoff

    def transition_handoff(
        self,
        conversation_id: int,
        new_state: HandoffState,
        assigned_to: str | None = None,
        resolution_notes: str | None = None,
    ) -> WhatsAppHandoff | None:
        """Transition a handoff to a new state."""
        handoff = self.get_handoff(conversation_id)
        if handoff is None:
            return None
        now = datetime.now(timezone.utc)
        handoff.state = new_state
        if assigned_to:
            handoff.assigned_to = assigned_to
        if resolution_notes:
            handoff.resolution_notes = resolution_notes
        if new_state == HandoffState.HUMAN_ACTIVE:
            handoff.activated_at = now
        elif new_state == HandoffState.RESOLVED:
            handoff.resolved_at = now
        handoff.updated_at = now
        self.db.flush()
        return handoff

    def list_handoffs(
        self, state: HandoffState | None = None, limit: int = 50
    ) -> list[WhatsAppHandoff]:
        """List handoffs, optionally filtered by state."""
        stmt = select(WhatsAppHandoff)
        if state:
            stmt = stmt.where(WhatsAppHandoff.state == state)
        stmt = stmt.order_by(WhatsAppHandoff.created_at.desc()).limit(limit)
        return list(self.db.execute(stmt).scalars().all())
