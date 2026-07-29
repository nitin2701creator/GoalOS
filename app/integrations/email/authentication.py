"""Authentication seams for email provider implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.integrations.email.config import EmailConfig

logger = logging.getLogger(__name__)


class EmailAuthenticator(ABC):
    """Strategy interface for supplying credentials to an email provider."""

    @abstractmethod
    def authenticate(self, config: EmailConfig) -> None:
        """Authenticate a configured provider without persisting credentials."""


class OAuthAuthenticator(EmailAuthenticator):
    """Extension point for OAuth-capable email providers."""

    def authenticate(self, config: EmailConfig) -> None:
        logger.info("OAuth authentication requested for email provider '%s'", config.provider)
        raise NotImplementedError("OAuth authentication requires a provider implementation")


class BasicAuthenticator(EmailAuthenticator):
    """Extension point for username/password-capable email providers."""

    def authenticate(self, config: EmailConfig) -> None:
        logger.info("Basic authentication requested for email provider '%s'", config.provider)
        raise NotImplementedError("Basic authentication requires a provider implementation")
