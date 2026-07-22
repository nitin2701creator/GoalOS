"""Gmail implementation of the provider-neutral email connector."""

from __future__ import annotations

from typing import Protocol

from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.email.authentication import EmailAuthenticator
from app.integrations.email.config import EmailConfig
from app.integrations.email.email_connector import EmailConnector
from app.integrations.email.models import EmailFolder, EmailMessage, EmailSearchResult
from app.integrations.email.providers.oauth import ConfiguredOAuthAuthenticator


class GmailService(Protocol):
    """Adapter around Gmail's API client, kept mockable and SDK-independent."""

    def health_check(self) -> ConnectorHealth: ...
    def list_folders(self) -> list[EmailFolder]: ...
    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]: ...
    def get_message(self, message_id: str) -> EmailMessage: ...
    def search_messages(self, query: str) -> EmailSearchResult: ...
    def send_message(self, message: EmailMessage) -> EmailMessage: ...
    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage: ...


class UnavailableGmailService:
    """Safe default used until a Gmail SDK adapter is supplied."""

    @staticmethod
    def _unavailable() -> None:
        raise NotImplementedError("Gmail API service has not been configured")

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "Gmail API service is not configured.")

    def list_folders(self) -> list[EmailFolder]: self._unavailable()
    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]: self._unavailable()
    def get_message(self, message_id: str) -> EmailMessage: self._unavailable()
    def search_messages(self, query: str) -> EmailSearchResult: self._unavailable()
    def send_message(self, message: EmailMessage) -> EmailMessage: self._unavailable()
    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage: self._unavailable()


class GmailProvider(EmailConnector):
    """Concrete Gmail connector with injectable OAuth and API adapters."""

    def __init__(
        self,
        config: EmailConfig | None = None,
        authenticator: EmailAuthenticator | None = None,
        service: GmailService | None = None,
    ) -> None:
        gmail_config = config or EmailConfig(provider="gmail")
        if gmail_config.provider.casefold() != "gmail":
            raise ValueError("GmailProvider requires EmailConfig(provider='gmail')")
        super().__init__(
            config=gmail_config,
            authenticator=authenticator or ConfiguredOAuthAuthenticator(),
            connector_name="gmail",
            description="Gmail email provider",
        )
        self.service = service or UnavailableGmailService()

    def connect(self) -> None:
        self.authenticate()
        self._set_health(self.service.health_check())

    def health_check(self) -> ConnectorHealth:
        return self._set_health(self.service.health_check())

    def list_folders(self) -> list[EmailFolder]: return self.service.list_folders()
    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]: return self.service.list_messages(folder_id)
    def get_message(self, message_id: str) -> EmailMessage: return self.service.get_message(message_id)
    def search_messages(self, query: str) -> EmailSearchResult: return self.service.search_messages(query)
    def send_message(self, message: EmailMessage) -> EmailMessage: return self.service.send_message(message)
    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage: return self.service.reply(message_id, message)
