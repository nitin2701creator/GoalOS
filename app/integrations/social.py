"""Social media capability layer: provider contracts, no fake implementations.

``SocialConnector`` declares the full social-media capability surface GoalOS
plans to support (Meta/Facebook/Instagram, LinkedIn, X, Reddit — create,
publish, get, analytics) so the capability registry can resolve those names,
but it does NOT implement provider calls: there is no existing social
provider framework in GoalOS, and no credentials are invented. Every
capability honestly reports itself unavailable (``INTEGRATION_NOT_CONFIGURED``
through the capability engine) until a real provider connector is wired.

Publishing capabilities additionally declare ``PUBLISH_SOCIAL`` as their
required permission and are marked approval-required at the capability
definition level, so even once a provider is wired they can never publish
silently — they must be executed through the approved workflow path with the
explicit permission granted.

The connector intentionally reads no API keys, URLs, or OAuth tokens: it
reports ``Not Configured`` always, because no provider connection exists.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.agents.permissions import Permission
from app.integrations.exceptions import CapabilityUnavailableError
from app.integrations.integration_connector import IntegrationConnector

#: Provider slug → human name for honest availability messages.
_PROVIDER_NAMES: dict[str, str] = {
    "meta": "Meta/Facebook/Instagram",
    "linkedin": "LinkedIn",
    "x": "X (Twitter)",
    "reddit": "Reddit",
}

_ACTIONS = ("create_post", "publish_post", "get_post", "get_insights")

_READ_ACTIONS = frozenset({"get_post", "get_insights"})


class SocialConnector(IntegrationConnector):
    """Declared social capabilities with honest Not Configured availability.

    No provider calls are implemented: every capability reports itself
    unavailable (no provider connector or credentials exist), so the
    execution runtime persists ``INTEGRATION_NOT_CONFIGURED`` rather than a
    fabricated result.
    """

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        f"social.{provider}.{action}": (
            Permission.READ_SOCIAL if action in _READ_ACTIONS else Permission.PUBLISH_SOCIAL
        )
        for provider in _PROVIDER_NAMES
        for action in _ACTIONS
    }

    def __init__(self) -> None:
        super().__init__(
            name="social",
            description="Social media capability contracts (no provider configured)",
        )

    def _capabilities(self) -> tuple[str, ...]:
        return tuple(
            f"social.{provider}.{action}"
            for provider in _PROVIDER_NAMES
            for action in _ACTIONS
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        return (
            ConnectorHealthStatus.NOT_CONFIGURED,
            "no social media provider connector is configured",
        )

    def capability_available(self, capability: str) -> tuple[bool, str]:
        """Report honest per-provider availability (always unavailable)."""
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"
        provider = capability.split(".", 2)[1]
        name = _PROVIDER_NAMES.get(provider, provider)
        return (
            False,
            (
                f"social provider '{name}' is not configured "
                "(no provider connector/credentials are wired)"
            ),
        )

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        # Never reached: capability_available reports unavailable for every
        # capability, so the capability engine blocks dispatch first.
        raise CapabilityUnavailableError(
            f"capability '{capability}' has no provider implementation; "
            "reporting INTEGRATION_NOT_CONFIGURED"
        )
