"""Provider-neutral foundation for GoalOS email integrations."""

from __future__ import annotations

import logging

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.email.authentication import EmailAuthenticator
from app.integrations.email.config import EmailConfig
from app.integrations.email.models import EmailFolder, EmailMessage, EmailSearchResult

logger = logging.getLogger(__name__)


class EmailConnector(BaseConnector):
    """Email connector contract, ready for provider-specific transports.

    This base implementation intentionally performs no network or provider API
    calls. Future providers can extend it while retaining its configuration,
    lifecycle, model, and authentication contracts.
    """

    def __init__(
        self,
        config: EmailConfig | None = None,
        authenticator: EmailAuthenticator | None = None,
        *,
        connector_name: str = "email",
        description: str = "Provider-neutral email connector",
    ) -> None:
        super().__init__(name=connector_name, description=description)
        self.config = config or EmailConfig()
        self.authenticator = authenticator

    def connect(self) -> None:
        logger.info("Email connection requested for provider '%s'", self.config.provider)
        self._not_implemented("connect")

    def authenticate(self) -> None:
        if self.authenticator is None:
            self._not_implemented("authenticate")
        self.authenticator.authenticate(self.config)

    def disconnect(self) -> None:
        logger.info("Email connector disconnected for provider '%s'", self.config.provider)
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED))

    def health_check(self) -> ConnectorHealth:
        return self._set_health(
            ConnectorHealth(self.status, "Email provider transport is not configured.")
        )

    def list_folders(self) -> list[EmailFolder]:
        self._not_implemented("list_folders")

    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]:
        self._not_implemented("list_messages")

    def get_message(self, message_id: str) -> EmailMessage:
        self._not_implemented("get_message")

    def search_messages(self, query: str) -> EmailSearchResult:
        self._not_implemented("search_messages")

    def send_message(self, message: EmailMessage) -> EmailMessage:
        self._not_implemented("send_message")

    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage:
        self._not_implemented("reply")

    def get_capabilities(self) -> tuple[str, ...]:
        return (
            "authenticate",
            "list_folders",
            "list_messages",
            "get_message",
            "search_messages",
            "send_message",
            "reply",
        )

    @staticmethod
    def _not_implemented(operation: str) -> None:
        raise NotImplementedError(
            f"Email connector operation '{operation}' requires a provider implementation"
        )
