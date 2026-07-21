"""Typed, provider-neutral email data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AttachmentMetadata:
    """Metadata for an email attachment without loading its content."""

    filename: str
    content_type: str | None = None
    size: int | None = None
    content_id: str | None = None


@dataclass(frozen=True, slots=True)
class EmailFolder:
    """A mailbox folder or provider label."""

    id: str
    name: str
    message_count: int | None = None
    unread_count: int | None = None


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """Normalized representation of an email message."""

    id: str
    subject: str = ""
    sender: str | None = None
    recipients: tuple[str, ...] = ()
    body_text: str | None = None
    body_html: str | None = None
    sent_at: datetime | None = None
    received_at: datetime | None = None
    folder_id: str | None = None
    attachments: tuple[AttachmentMetadata, ...] = field(default_factory=tuple)
    in_reply_to: str | None = None


@dataclass(frozen=True, slots=True)
class EmailSearchResult:
    """A provider-independent page of message-search results."""

    query: str
    messages: tuple[EmailMessage, ...] = field(default_factory=tuple)
    total_count: int | None = None
