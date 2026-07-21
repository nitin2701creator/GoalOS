"""Provider-independent configuration for email connectors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmailConfig:
    """Connection settings shared by email providers and protocols.

    Credentials deliberately do not belong here. They are supplied by an
    ``EmailAuthenticator`` implementation so configuration can be safely
    stored, logged, and shared without exposing secrets.
    """

    provider: str = "generic"
    server: str | None = None
    port: int | None = None
    ssl: bool = True
    timeout: float = 30.0

    def __post_init__(self) -> None:
        """Validate settings before a transport implementation consumes them."""

        if not isinstance(self.provider, str) or not self.provider.strip():
            raise ValueError("provider is required")
        if self.server is not None and (
            not isinstance(self.server, str) or not self.server.strip()
        ):
            raise ValueError("server must be a non-empty string when provided")
        if self.port is not None and (
            isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535
        ):
            raise ValueError("port must be between 1 and 65535 when provided")
        if not isinstance(self.ssl, bool):
            raise ValueError("ssl must be a boolean")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("timeout must be a positive number")

        object.__setattr__(self, "provider", self.provider.strip())
        if self.server is not None:
            object.__setattr__(self, "server", self.server.strip())
        object.__setattr__(self, "timeout", float(self.timeout))
