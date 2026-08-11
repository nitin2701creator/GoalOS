"""Tests for Gmail's concrete email-provider adapter."""

from __future__ import annotations

import pytest

from app.integrations import ConnectorHealth, ConnectorHealthStatus, ConnectorRegistry
from app.integrations.email import EmailConfig, EmailConnector, EmailFolder, EmailMessage, EmailSearchResult
from app.integrations.email.providers.gmail_provider import GmailProvider
from app.integrations.email.providers.credentials import OAuthClientCredentials
from app.integrations.email.providers.oauth import ConfiguredOAuthAuthenticator
from app.integrations.email.providers.token_store import InMemoryTokenStore, OAuthToken


class FakeAuthorizationClient:
    def __init__(self) -> None:
        self.calls: list[tuple[OAuthClientCredentials, OAuthToken | None]] = []

    def authorize(self, credentials: OAuthClientCredentials, existing_token: OAuthToken | None) -> OAuthToken:
        self.calls.append((credentials, existing_token))
        return OAuthToken("test-access-token")


class FakeGmailService:
    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(ConnectorHealthStatus.HEALTHY)

    def list_folders(self) -> list[EmailFolder]:
        return [EmailFolder(id="INBOX", name="Inbox")]

    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]:
        return [EmailMessage(id="message-1", folder_id=folder_id)]

    def get_message(self, message_id: str) -> EmailMessage:
        return EmailMessage(id=message_id)

    def search_messages(self, query: str) -> EmailSearchResult:
        return EmailSearchResult(query=query)

    def send_message(self, message: EmailMessage) -> EmailMessage:
        return message

    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage:
        return EmailMessage(id="reply-1", in_reply_to=message_id, subject=message.subject)


def test_gmail_provider_initializes_as_email_connector() -> None:
    provider = GmailProvider()

    assert isinstance(provider, EmailConnector)
    assert provider.name == "gmail"
    assert provider.config == EmailConfig(provider="gmail")
    assert provider.status is ConnectorHealthStatus.DISCONNECTED


def test_gmail_provider_uses_injected_oauth_abstraction() -> None:
    credentials = OAuthClientCredentials(client_id="client-id", scopes=("mail.google.com",))
    authorization_client = FakeAuthorizationClient()
    token_store = InMemoryTokenStore()
    provider = GmailProvider(
        authenticator=ConfiguredOAuthAuthenticator(credentials, authorization_client, token_store)
    )

    provider.authenticate()

    assert authorization_client.calls == [(credentials, None)]
    assert token_store.load("gmail") == OAuthToken("test-access-token")


def test_gmail_provider_is_connector_registry_compatible() -> None:
    registry = ConnectorRegistry()
    provider = GmailProvider()

    registry.register(provider)

    assert registry.get_connector("gmail") is provider


def test_gmail_provider_delegates_email_operations_to_injected_service() -> None:
    provider = GmailProvider(service=FakeGmailService())
    message = EmailMessage(id="draft-1", subject="Hello")

    assert provider.health_check().is_healthy
    assert provider.list_folders()[0].id == "INBOX"
    assert provider.list_messages("INBOX")[0].folder_id == "INBOX"
    assert provider.get_message("message-2").id == "message-2"
    assert provider.search_messages("from:me").query == "from:me"
    assert provider.send_message(message) is message
    assert provider.reply("message-2", message).in_reply_to == "message-2"


def test_gmail_provider_has_safe_placeholder_api_behavior_without_sdk_or_credentials() -> None:
    provider = GmailProvider()

    with pytest.raises(RuntimeError, match="credentials"):
        provider.authenticate()
    with pytest.raises(NotImplementedError, match="Gmail API service"):
        provider.list_folders()
    assert provider.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
