"""Concrete implementations of the provider-neutral email connector."""

from app.integrations.email.providers.gmail_provider import (
    GmailProvider,
    GmailService,
    UnavailableGmailService,
)

__all__ = ["GmailProvider", "GmailService", "UnavailableGmailService"]
