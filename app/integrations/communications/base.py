"""Abstract base for GoalOS communication providers.

Implement this interface to add a new voice/SMS provider (Twilio, Plivo,
Exotel, Knowlarity, etc.). The factory selects the active provider from
the COMMUNICATION_PROVIDER environment variable.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from app.integrations.communications.models import (
    SmsRequest,
    SmsResponse,
    StatusEvent,
    VoiceCallRequest,
    VoiceCallResponse,
    normalize_e164,
)


@dataclass(frozen=True, slots=True)
class CommunicationConfig:
    """Encapsulated provider configuration (secrets are read once from env)."""

    provider: str
    account_id: str
    auth_token: str
    from_number: str
    extra: dict[str, str | None] = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        """Return True only if all required credentials are non-empty."""
        return bool(self.account_id and self.auth_token and self.from_number)

    def redacted(self) -> dict[str, str]:
        """Return config with secrets masked (never expose to API/logs)."""
        from app.integrations.communications.models import redact_credentials

        # Provider name is not a secret — pass it through unchanged
        secrets = {
            "account_id": self.account_id,
            "auth_token": self.auth_token,
            "from_number": self.from_number,
        }
        secrets.update(self.extra)
        masked = redact_credentials(secrets)
        masked["provider"] = self.provider
        return masked


class BaseCommunicationAdapter(abc.ABC):
    """Abstract foundation for a voice/SMS communication adapter.

    Subclasses own provider-specific HTTP transport and auth. The framework
    manages identity, health, and configuration consistently.
    """

    name: str

    def __init__(self, config: CommunicationConfig) -> None:
        self.config = config
        self._is_configured = config.is_configured

    @property
    def is_configured(self) -> bool:
        return self._is_configured

    def normalize_number(self, number: str) -> str:
        """Normalize a phone number to E.164 format."""
        return normalize_e164(number)

    @abc.abstractmethod
    def make_voice_call(self, request: VoiceCallRequest) -> VoiceCallResponse:
        """Initiate an outbound voice call.

        Returns a VoiceCallResponse with the provider's status and call_id.
        On configuration errors, returns a NO_PROVIDER or FAILED status
        without raising.
        """

    @abc.abstractmethod
    def send_sms(self, request: SmsRequest) -> SmsResponse:
        """Send an outbound SMS message.

        Returns an SmsResponse with the provider's status and message_id.
        On configuration errors, returns a NO_PROVIDER or FAILED status
        without raising.
        """

    @abc.abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> StatusEvent | None:
        """Parse a provider-specific webhook payload into a StatusEvent.

        Returns None if the payload is not recognized.
        """

    def get_status(self, provider_id: str) -> StatusEvent | None:
        """Optionally poll provider for current status (default: not supported)."""
        return None
