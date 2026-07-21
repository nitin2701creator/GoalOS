"""Provider-neutral email integration primitives."""

from app.integrations.email.authentication import (
    BasicAuthenticator,
    EmailAuthenticator,
    OAuthAuthenticator,
)
from app.integrations.email.config import EmailConfig
from app.integrations.email.email_connector import EmailConnector
from app.integrations.email.models import (
    AttachmentMetadata,
    EmailFolder,
    EmailMessage,
    EmailSearchResult,
)

__all__ = [
    "AttachmentMetadata",
    "BasicAuthenticator",
    "EmailAuthenticator",
    "EmailConfig",
    "EmailConnector",
    "EmailFolder",
    "EmailMessage",
    "EmailSearchResult",
    "OAuthAuthenticator",
]
