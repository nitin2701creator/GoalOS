"""Abstract base for GoalOS WhatsApp providers.

Implement this interface to add a new WhatsApp backend (OpenWA,
Meta Cloud API, etc.). The factory selects the active provider from
the WHATSAPP_PROVIDER environment variable.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from app.integrations.whatsapp.models import (
    SendMessageRequest,
    SendMessageResponse,
    SendTemplateRequest,
    SendTemplateResponse,
    TemplateStatus,
    WhatsAppWebhookEvent,
)


@dataclass(frozen=True, slots=True)
class WhatsAppConfig:
    """Encapsulated provider configuration (secrets read once from env)."""

    provider: str
    api_base_url: str = ""
    auth_token: str = ""
    webhook_secret: str = ""
    extra: dict[str, str | None] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Return True only if required credentials are non-empty."""
        return bool(self.api_base_url)

    def redacted(self) -> dict[str, str]:
        """Return config with secrets masked."""
        from app.integrations.whatsapp.models import redact_whatsapp_config

        secrets: dict[str, Any] = {
            "api_base_url": self.api_base_url,
            "auth_token": self.auth_token,
            "webhook_secret": self.webhook_secret,
        }
        secrets.update(self.extra)
        masked = redact_whatsapp_config(secrets)
        masked["provider"] = self.provider
        return masked


class BaseWhatsAppAdapter(abc.ABC):
    """Abstract foundation for a WhatsApp adapter.

    Subclasses own provider-specific HTTP transport and auth. The framework
    manages identity, health, and configuration consistently.
    """

    name: str

    def __init__(self, config: WhatsAppConfig) -> None:
        self.config = config
        self._is_configured = config.is_configured

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    @abc.abstractmethod
    def send_message(self, request: SendMessageRequest) -> SendMessageResponse:
        """Send an outbound WhatsApp message.

        Returns a SendMessageResponse with the provider's status and ID.
        On configuration errors, returns a NO_PROVIDER or FAILED status
        without raising.
        """

    @abc.abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> WhatsAppWebhookEvent | None:
        """Parse a provider-specific webhook payload into a normalized event.

        Returns None if the payload is not recognized.
        """

    def verify_webhook(self, payload: bytes, signature: str | None) -> bool:
        """Verify a webhook signature (provider-specific).

        Default implementation accepts all webhooks (no verification).
        Subclasses should override when the provider supports signatures.
        """
        return True

    def send_template(self, request: SendTemplateRequest) -> SendTemplateResponse:
        """Send an approved template message.

        Default implementation returns FAILED — subclasses override.
        """
        return SendTemplateResponse(
            provider=self.name,
            status=TemplateStatus.FAILED,
            error="Template sending not implemented for this provider",
        )

    def get_status(self) -> dict[str, Any]:
        """Return provider health/status information."""
        return {
            "provider": self.name,
            "configured": self.is_configured,
            "status": "ready" if self.is_configured else "not_configured",
        }
