"""Social media capability layer with real provider delegation.

``SocialConnector`` declares the full social-media capability surface GoalOS
supports (Meta/Facebook/Instagram, LinkedIn, X, Reddit) and delegates to
real provider connectors when they are configured.

Each provider connector is registered separately and implements the actual
API calls. ``SocialConnector`` acts as a unified facade: when a provider
is configured and registered, capabilities dispatch through the real
connector. When unconfigured, capabilities honestly report
``INTEGRATION_NOT_CONFIGURED``.

Publishing capabilities additionally declare ``PUBLISH_SOCIAL`` as their
required permission and are marked approval-required at the capability
definition level.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import CapabilityUnavailableError
from app.integrations.integration_connector import IntegrationConnector

logger = logging.getLogger(__name__)

#: Provider slug → human name for honest availability messages.
_PROVIDER_NAMES: dict[str, str] = {
    "meta": "Meta/Facebook/Instagram",
    "linkedin": "LinkedIn",
    "x": "X (Twitter)",
    "reddit": "Reddit",
}

#: Provider slug → (read capabilities, write capabilities)
_PROVIDER_CAPABILITIES: dict[str, tuple[list[str], list[str]]] = {
    "meta": (
        ["get_post", "get_insights", "list_pages", "list_instagram_accounts", "get_page_info", "get_page_insights", "get_instagram_media", "get_instagram_insights"],
        ["create_post", "publish_post", "publish_to_instagram", "delete_post"],
    ),
    "linkedin": (
        ["get_post", "get_analytics", "list_organizations"],
        ["create_post", "publish_post"],
    ),
    "x": (
        ["get_post", "get_analytics", "get_account"],
        ["create_post", "publish_post", "delete_post"],
    ),
    "reddit": (
        ["get_post", "get_account", "list_subreddits"],
        ["create_post", "publish_post", "create_comment"],
    ),
}


class SocialConnector(IntegrationConnector):
    """Unified social media facade with real provider delegation.

    Provider connectors register themselves via ``register_provider()``.
    When a provider is registered and healthy, capabilities dispatch
    through the real connector. When unconfigured, capabilities report
    ``INTEGRATION_NOT_CONFIGURED`` honestly.
    """

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {}

    def __init__(self) -> None:
        super().__init__(
            name="social",
            description="Social media unified facade (Meta, LinkedIn, X, Reddit)",
        )
        self._providers: dict[str, IntegrationConnector] = {}
        # Build capability permissions from provider definitions
        self._build_capability_permissions()

    def _build_capability_permissions(self) -> None:
        """Build CAPABILITY_PERMISSIONS from provider definitions."""
        for provider, (read_caps, write_caps) in _PROVIDER_CAPABILITIES.items():
            for cap in read_caps:
                self.CAPABILITY_PERMISSIONS[f"social.{provider}.{cap}"] = Permission.READ_SOCIAL
            for cap in write_caps:
                self.CAPABILITY_PERMISSIONS[f"social.{provider}.{cap}"] = Permission.PUBLISH_SOCIAL

    def register_provider(self, name: str, connector: IntegrationConnector) -> None:
        """Register a real social provider connector."""
        if name in _PROVIDER_NAMES:
            self._providers[name] = connector
            logger.info("Registered social provider '%s' (%s)", name, connector.name)

    def get_provider(self, name: str) -> IntegrationConnector | None:
        """Return a registered provider connector by name."""
        return self._providers.get(name)

    def list_providers(self) -> dict[str, dict[str, Any]]:
        """Return the status and capabilities of all registered providers."""
        result = {}
        for name, human_name in _PROVIDER_NAMES.items():
            connector = self._providers.get(name)
            if connector is None:
                result[name] = {
                    "name": name,
                    "display_name": human_name,
                    "registered": False,
                    "configured": False,
                    "status": "not_registered",
                    "capabilities": [],
                }
            else:
                health = connector.health_check()
                result[name] = {
                    "name": name,
                    "display_name": human_name,
                    "registered": True,
                    "configured": connector.is_configured,
                    "status": health.status.value,
                    "message": health.message,
                    "capabilities": list(connector.get_capabilities()),
                }
        return result

    def _capabilities(self) -> tuple[str, ...]:
        """Return all social capabilities across all providers."""
        caps = []
        for provider, (read_caps, write_caps) in _PROVIDER_CAPABILITIES.items():
            for cap in read_caps:
                caps.append(f"social.{provider}.{cap}")
            for cap in write_caps:
                caps.append(f"social.{provider}.{cap}")
        return tuple(sorted(caps))

    def _configuration_status(self) -> tuple[Any, str | None]:
        """Report configuration based on registered providers."""
        configured = [
            name for name, conn in self._providers.items() if conn.is_configured
        ]
        if configured:
            return (
                ConnectorHealthStatus.HEALTHY,
                f"configured providers: {', '.join(sorted(configured))}",
            )
        return (
            ConnectorHealthStatus.NOT_CONFIGURED,
            "no social media provider connector is configured",
        )

    def capability_available(self, capability: str) -> tuple[bool, str]:
        """Check capability availability through provider delegation."""
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"

        # Parse provider from capability name (e.g., "social.meta.publish_post" -> "meta")
        parts = capability.split(".")
        if len(parts) < 3:
            return False, f"malformed capability: {capability}"
        provider_name = parts[1]

        connector = self._providers.get(provider_name)
        if connector is None:
            human_name = _PROVIDER_NAMES.get(provider_name, provider_name)
            return (
                False,
                f"social provider '{human_name}' is not registered",
            )

        # Check if the connector is configured
        if not connector.is_configured:
            available, reason = connector.capability_available(capability)
            return available, reason

        # Map social.* capability to the provider's native capability
        native_capability = self._map_capability(provider_name, capability)
        if native_capability is None:
            return False, f"capability '{capability}' has no provider mapping"

        return connector.capability_available(native_capability)

    def execute(self, capability: str, params=None, *, permissions=None) -> dict[str, Any]:
        """Execute a social capability with delegation to providers.

        Passes permissions through to the underlying provider connector
        so that permission enforcement happens at both levels.
        """
        # Import here to avoid circular imports at module level
        from app.integrations.integration_connector import IntegrationConnector

        # Check capability availability first
        available, reason = self.capability_available(capability)
        if not available:
            raise CapabilityUnavailableError(
                f"integration '{self.name}' cannot execute '{capability}': {reason}"
            )

        # Check our own permissions
        required = self.CAPABILITY_PERMISSIONS.get(capability)
        if required is not None:
            granted = set(permissions or ())
            if required not in granted:
                from app.integrations.exceptions import PermissionDeniedError
                raise PermissionDeniedError(
                    f"capability '{capability}' requires permission "
                    f"'{required.value}', which was not granted"
                )

        # Dispatch to provider with permissions passed through
        return self._dispatch(capability, dict(params or {}), permissions=permissions)

    def _dispatch(self, capability: str, params: dict[str, Any], permissions=None) -> dict[str, Any]:
        """Dispatch to the appropriate provider connector."""
        parts = capability.split(".")
        if len(parts) < 3:
            raise CapabilityUnavailableError(f"malformed capability: {capability}")
        provider_name = parts[1]

        connector = self._providers.get(provider_name)
        if connector is None:
            raise CapabilityUnavailableError(
                f"social provider '{provider_name}' is not registered; "
                "reporting INTEGRATION_NOT_CONFIGURED"
            )

        native_capability = self._map_capability(provider_name, capability)
        if native_capability is None:
            raise CapabilityUnavailableError(
                f"capability '{capability}' has no provider mapping"
            )

        return connector.execute(native_capability, params, permissions=permissions)

    def _map_capability(self, provider: str, social_capability: str) -> str | None:
        """Map a social.* capability to the provider's native capability name."""
        # social.meta.publish_post -> meta_social.publish_post
        # social.linkedin.get_post -> linkedin.get_post
        parts = social_capability.split(".")
        action = parts[2] if len(parts) >= 3 else ""

        mapping = {
            "meta": {
                "get_post": "meta_social.get_post",
                "get_insights": "meta_social.get_page_insights",
                "list_pages": "meta_social.list_pages",
                "list_instagram_accounts": "meta_social.list_instagram_accounts",
                "get_page_info": "meta_social.get_page_info",
                "get_page_insights": "meta_social.get_page_insights",
                "create_post": "meta_social.publish_post",
                "publish_post": "meta_social.publish_post",
            },
            "linkedin": {
                "get_post": "linkedin.get_post",
                "get_analytics": "linkedin.get_analytics",
                "list_organizations": "linkedin.get_org_organizations",
                "create_post": "linkedin.create_text_post",
                "publish_post": "linkedin.create_text_post",
            },
            "x": {
                "get_post": "twitter.get_tweet",
                "get_analytics": "twitter.get_tweet_metrics",
                "get_account": "twitter.get_me",
                "create_post": "twitter.create_tweet",
                "publish_post": "twitter.create_tweet",
                "delete_post": "twitter.delete_tweet",
            },
            "reddit": {
                "get_post": "reddit.get_post",
                "get_account": "reddit.get_me",
                "list_subreddits": "reddit.list_subreddits",
                "create_post": "reddit.submit_post",
                "publish_post": "reddit.submit_post",
                "create_comment": "reddit.submit_comment",
            },
        }
        return mapping.get(provider, {}).get(action)
