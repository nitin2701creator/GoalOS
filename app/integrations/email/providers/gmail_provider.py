"""Gmail implementation of the provider-neutral email connector."""

from __future__ import annotations

from typing import Any, ClassVar, Protocol

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.email.authentication import EmailAuthenticator
from app.integrations.email.config import EmailConfig
from app.integrations.email.email_connector import EmailConnector
from app.integrations.email.models import (
    AttachmentMetadata,
    EmailFolder,
    EmailMessage,
    EmailSearchResult,
)
from app.integrations.email.providers.gmail_rest_service import (
    GmailRESTService,
    message_from_dict,
)
from app.integrations.email.providers.oauth import ConfiguredOAuthAuthenticator
from app.integrations.exceptions import (
    CapabilityUnavailableError,
    PermissionDeniedError,
)


class GmailService(Protocol):
    """Adapter around Gmail's API client, kept mockable and SDK-independent."""

    def health_check(self) -> ConnectorHealth: ...
    def list_folders(self) -> list[EmailFolder]: ...
    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]: ...
    def get_message(self, message_id: str) -> EmailMessage: ...
    def search_messages(self, query: str) -> EmailSearchResult: ...
    def create_draft(self, message: EmailMessage) -> EmailMessage: ...
    def send_message(self, message: EmailMessage) -> EmailMessage: ...
    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage: ...
    def list_threads(self, query: str = "", max_results: int = 20) -> list[EmailMessage]: ...
    def get_thread(self, thread_id: str) -> dict[str, Any]: ...
    def list_attachments(self, message_id: str) -> list[AttachmentMetadata]: ...
    def get_attachment(self, message_id: str, attachment_id: str) -> dict[str, Any]: ...


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
    def create_draft(self, message: EmailMessage) -> EmailMessage: self._unavailable()
    def send_message(self, message: EmailMessage) -> EmailMessage: self._unavailable()
    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage: self._unavailable()
    def list_threads(self, query: str = "", max_results: int = 20) -> list[EmailMessage]: self._unavailable()
    def get_thread(self, thread_id: str) -> dict[str, Any]: self._unavailable()
    def list_attachments(self, message_id: str) -> list[AttachmentMetadata]: self._unavailable()
    def get_attachment(self, message_id: str, attachment_id: str) -> dict[str, Any]: self._unavailable()


class GmailProvider(EmailConnector):
    """Concrete Gmail connector with injectable OAuth and API adapters.

    In addition to the provider-neutral email contract, the provider
    exposes the GoalOS capability names (``email.search``, ``email.read``,
    ``email.draft``, ``email.send``) with explicit permission
    enforcement — ``email.send`` never runs without ``SEND_EMAIL``.
    """

    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "email.search": Permission.READ_EMAIL,
        "email.read": Permission.READ_EMAIL,
        "email.draft": Permission.SEND_EMAIL,
        "email.send": Permission.SEND_EMAIL,
        "gmail.health": Permission.READ_EMAIL,
        "gmail.search_messages": Permission.READ_EMAIL,
        "gmail.get_message": Permission.READ_EMAIL,
        "gmail.get_thread": Permission.READ_EMAIL,
        "gmail.list_threads": Permission.READ_EMAIL,
        "gmail.list_attachments": Permission.READ_EMAIL,
        "gmail.get_attachment": Permission.READ_EMAIL,
        "gmail.send_message": Permission.SEND_EMAIL,
        "gmail.reply_to_thread": Permission.SEND_EMAIL,
    }

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
        self.service = service or self._default_service()

    def _default_service(self) -> GmailService:
        """Build a real REST service when credentials are configured."""
        service = GmailRESTService()
        return service if service.is_configured else UnavailableGmailService()

    @property
    def capabilities(self) -> tuple[str, ...]:
        return (
            "email.search",
            "email.read",
            "email.draft",
            "email.send",
            "gmail.health",
            "gmail.search_messages",
            "gmail.get_message",
            "gmail.get_thread",
            "gmail.list_threads",
            "gmail.send_message",
            "gmail.reply_to_thread",
            "gmail.list_attachments",
            "gmail.get_attachment",
        )

    @property
    def is_configured(self) -> bool:
        return not isinstance(self.service, UnavailableGmailService)

    def capability_available(self, capability: str) -> tuple[bool, str]:
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"
        if isinstance(self.service, UnavailableGmailService):
            return (
                False,
                (
                    "Gmail API service is not configured "
                    "(GOALOS_GMAIL_CLIENT_ID + GOALOS_GMAIL_REFRESH_TOKEN)"
                ),
            )
        return True, "available"

    def execute(
        self,
        capability: str,
        params: dict[str, Any] | None = None,
        *,
        permissions: set[Permission] | frozenset[Permission] | None = None,
    ) -> dict[str, Any]:
        """Invoke an email capability with explicit permission enforcement."""
        available, reason = self.capability_available(capability)
        if not available:
            raise CapabilityUnavailableError(
                f"integration 'gmail' cannot execute '{capability}': {reason}"
            )
        required = self.CAPABILITY_PERMISSIONS.get(capability)
        if required is not None and required not in set(permissions or ()):
            raise PermissionDeniedError(
                f"capability '{capability}' requires permission "
                f"'{required.value}', which was not granted"
            )
        params = params or {}
        if capability in ("email.search", "gmail.search_messages"):
            return {"query": params["query"], "messages": self._search(params["query"])}
        if capability in ("email.read", "gmail.get_message"):
            return {"message": self._message(params["message_id"])}
        if capability == "email.draft":
            draft = self.create_draft(message_from_dict(params["message"]))
            return {"draft_id": draft.id, "subject": draft.subject}
        if capability in ("email.send", "gmail.send_message"):
            sent = self.send_message(message_from_dict(params["message"]))
            return {"message_id": sent.id, "subject": sent.subject}
        if capability == "gmail.health":
            return self._health()
        if capability == "gmail.get_thread":
            return {"thread": self.service.get_thread(params["thread_id"])}
        if capability == "gmail.list_threads":
            threads = self.service.list_threads(
                params.get("query") or "", int(params.get("max_results") or 20)
            )
            return {
                "query": params.get("query") or "",
                "threads": [
                    {"id": thread.id, "snippet": thread.body_text} for thread in threads
                ],
            }
        if capability == "gmail.reply_to_thread":
            sent = self.service.reply(
                params["message_id"], message_from_dict(params.get("message") or {})
            )
            return {"message_id": sent.id, "subject": sent.subject}
        if capability == "gmail.list_attachments":
            attachments = self.service.list_attachments(params["message_id"])
            return {
                "message_id": params["message_id"],
                "attachments": [
                    {
                        "filename": item.filename,
                        "content_type": item.content_type,
                        "size": item.size,
                        "content_id": item.content_id,
                    }
                    for item in attachments
                ],
            }
        if capability == "gmail.get_attachment":
            return {
                "message_id": params["message_id"],
                "attachment": self.service.get_attachment(
                    params["message_id"], params["attachment_id"]
                ),
            }
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    def _health(self) -> dict[str, Any]:
        health = self.health_check()
        return {
            "integration": "gmail",
            "status": health.status.value,
            "configured": health.is_healthy,
            "message": health.message,
        }

    def connect(self) -> None:
        self.authenticate()
        self._set_health(self.service.health_check())

    def health_check(self) -> ConnectorHealth:
        if isinstance(self.service, UnavailableGmailService):
            return self._set_health(
                ConnectorHealth(
                    ConnectorHealthStatus.NOT_CONFIGURED,
                    "Gmail API service is not configured",
                )
            )
        return self._set_health(self.service.health_check())

    def list_folders(self) -> list[EmailFolder]: return self.service.list_folders()
    def list_messages(self, folder_id: str | None = None) -> list[EmailMessage]: return self.service.list_messages(folder_id)
    def get_message(self, message_id: str) -> EmailMessage: return self.service.get_message(message_id)
    def search_messages(self, query: str) -> EmailSearchResult: return self.service.search_messages(query)
    def create_draft(self, message: EmailMessage) -> EmailMessage: return self.service.create_draft(message)
    def send_message(self, message: EmailMessage) -> EmailMessage: return self.service.send_message(message)
    def reply(self, message_id: str, message: EmailMessage) -> EmailMessage: return self.service.reply(message_id, message)
    def list_threads(self, query: str = "", max_results: int = 20) -> list[EmailMessage]:
        return self.service.list_threads(query, max_results)
    def get_thread(self, thread_id: str) -> dict[str, Any]:
        return self.service.get_thread(thread_id)
    def list_attachments(self, message_id: str) -> list[AttachmentMetadata]:
        return self.service.list_attachments(message_id)
    def get_attachment(self, message_id: str, attachment_id: str) -> dict[str, Any]:
        return self.service.get_attachment(message_id, attachment_id)

    def _search(self, query: str) -> list[dict[str, Any]]:
        result = self.search_messages(query)
        return [
            {"id": message.id, "subject": message.subject, "snippet": message.body_text}
            for message in result.messages
        ]

    def _message(self, message_id: str) -> dict[str, Any]:
        message = self.get_message(message_id)
        return {
            "id": message.id,
            "subject": message.subject,
            "sender": message.sender,
            "recipients": list(message.recipients),
            "body": message.body_text,
        }
