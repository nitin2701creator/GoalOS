"""Tests for the provider-neutral email connector foundation."""

from __future__ import annotations

import pytest

from app.integrations import ConnectorHealthStatus, ConnectorRegistry
from app.integrations.email import (
    AttachmentMetadata,
    BasicAuthenticator,
    EmailConfig,
    EmailConnector,
    EmailFolder,
    EmailMessage,
    EmailSearchResult,
    OAuthAuthenticator,
)


def test_email_connector_initializes_with_safe_default_configuration() -> None:
    connector = EmailConnector()

    assert connector.name == "email"
    assert connector.config == EmailConfig()
    assert connector.status is ConnectorHealthStatus.DISCONNECTED
    assert connector.get_capabilities() == (
        "authenticate", "list_folders", "list_messages", "get_message",
        "search_messages", "send_message", "reply",
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"provider": " "}, "provider"),
        ({"server": " "}, "server"),
        ({"port": 0}, "port"),
        ({"port": 65536}, "port"),
        ({"timeout": 0}, "timeout"),
        ({"ssl": "true"}, "ssl"),
    ],
)
def test_email_config_validates_connection_settings(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        EmailConfig(**kwargs)  # type: ignore[arg-type]


def test_email_config_normalizes_valid_settings() -> None:
    config = EmailConfig(provider=" IMAP ", server=" mail.example.test ", port=993, timeout=10)

    assert config.provider == "IMAP"
    assert config.server == "mail.example.test"
    assert config.timeout == 10.0


def test_email_connector_is_registry_compatible() -> None:
    registry = ConnectorRegistry()
    connector = EmailConnector()

    registry.register(connector)

    assert registry.get_connector("email") is connector


def test_email_models_are_typed_provider_neutral_values() -> None:
    attachment = AttachmentMetadata(filename="report.pdf", size=42)
    message = EmailMessage(id="message-1", recipients=("to@example.test",), attachments=(attachment,))
    folder = EmailFolder(id="inbox", name="Inbox", unread_count=1)
    result = EmailSearchResult(query="report", messages=(message,), total_count=1)

    assert folder.name == "Inbox"
    assert result.messages == (message,)


def test_connector_methods_have_safe_placeholder_behavior() -> None:
    connector = EmailConnector()
    message = EmailMessage(id="draft-1")

    with pytest.raises(NotImplementedError, match="connect"):
        connector.connect()
    with pytest.raises(NotImplementedError, match="authenticate"):
        connector.authenticate()
    with pytest.raises(NotImplementedError, match="list_folders"):
        connector.list_folders()
    with pytest.raises(NotImplementedError, match="list_messages"):
        connector.list_messages()
    with pytest.raises(NotImplementedError, match="get_message"):
        connector.get_message("message-1")
    with pytest.raises(NotImplementedError, match="search_messages"):
        connector.search_messages("invoice")
    with pytest.raises(NotImplementedError, match="send_message"):
        connector.send_message(message)
    with pytest.raises(NotImplementedError, match="reply"):
        connector.reply("message-1", message)

    connector.disconnect()
    assert connector.health_check().status is ConnectorHealthStatus.DISCONNECTED


@pytest.mark.parametrize("authenticator", [OAuthAuthenticator(), BasicAuthenticator()])
def test_authentication_strategies_are_provider_extension_points(authenticator: object) -> None:
    with pytest.raises(NotImplementedError, match="provider implementation"):
        authenticator.authenticate(EmailConfig())  # type: ignore[union-attr]
