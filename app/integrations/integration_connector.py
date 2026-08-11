"""Base contract for GoalOS capability connectors.

An :class:`IntegrationConnector` wraps one external system (web, website
crawler, Gmail, WooCommerce, GA4, Meta Ads, scheduler). It extends the
existing :class:`BaseConnector` lifecycle and adds:

- stable ``capability`` names in the ``system.action`` convention
  (``web.fetch``, ``email.send``, ...);
- explicit permission requirements per capability, enforced before any
  dispatch — dangerous actions never run without authorization;
- configuration-aware health reporting (``Not Configured`` when required
  environment configuration is absent — never a fake success);
- a single ``execute(capability, params, permissions=...)`` entry point so
  agents and skills can discover and invoke integrations uniformly.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from collections.abc import Mapping
from typing import Any

from app.agents.permissions import Permission
from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.exceptions import (
    CapabilityUnavailableError,
    PermissionDeniedError,
)

logger = logging.getLogger(__name__)


class IntegrationConnector(BaseConnector):
    """Capability-oriented connector shared by all GoalOS integrations.

    Subclasses declare:

    - ``required_env_vars``: environment variable names that configure the
      integration (never their values);
    - ``CAPABILITY_PERMISSIONS``: mapping of capability name to the
      :class:`Permission` required to invoke it;
    - ``capabilities`` via the abstract :meth:`_capabilities` hook;
    - concrete dispatch in :meth:`_dispatch`.

    The base class never fabricates success: unconfigured connectors report
    ``Not Configured``, and unauthorized calls raise
    :class:`PermissionDeniedError`.
    """

    #: Environment variable names that configure this connector.
    required_env_vars: tuple[str, ...] = ()

    #: Capability name -> Permission required to invoke it.
    CAPABILITY_PERMISSIONS: Mapping[str, Permission] = {}

    def __init__(self, name: str, description: str) -> None:
        super().__init__(name=name, description=description)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    @property
    def is_configured(self) -> bool:
        """Return whether required environment configuration is present."""
        status, _ = self._configuration_status()
        return status is ConnectorHealthStatus.HEALTHY

    def configuration_health(self) -> ConnectorHealth:
        """Report configuration readiness without touching the network."""
        status, message = self._configuration_status()
        return self._set_health(ConnectorHealth(status, message))

    def _configuration_status(self) -> tuple[ConnectorHealthStatus, str | None]:
        """Return (status, message) derived from environment configuration.

        Subclasses override when configuration is not purely env-driven.
        The default requires every declared env var to be present.
        """
        missing = [name for name in self.required_env_vars if not self._env(name)]
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    # ------------------------------------------------------------------
    # Capability availability
    # ------------------------------------------------------------------
    def capability_available(self, capability: str) -> tuple[bool, str]:
        """Return (available, reason) for a single capability.

        The default requires the capability to be declared and the
        connector to be configured. Subclasses may narrow availability
        per capability (for example ``web.search`` needs a provider while
        ``web.fetch`` does not).
        """
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"
        if not self.is_configured:
            _, message = self._configuration_status()
            return False, message or f"integration '{self.name}' is not configured"
        return True, "available"

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute(
        self,
        capability: str,
        params: Mapping[str, Any] | None = None,
        *,
        permissions: set[Permission] | frozenset[Permission] | None = None,
    ) -> dict[str, Any]:
        """Invoke a capability with explicit permission enforcement.

        Args:
            capability: Capability name (``system.action``).
            params: Structured input parameters.
            permissions: Permissions granted to the caller; dangerous
                capabilities require their declared permission here.

        Returns:
            A structured result dictionary.

        Raises:
            CapabilityUnavailableError: If the capability is unsupported or
                the integration is not configured.
            PermissionDeniedError: If the capability requires a permission
                the caller has not granted.
        """
        available, reason = self.capability_available(capability)
        if not available:
            raise CapabilityUnavailableError(
                f"integration '{self.name}' cannot execute '{capability}': {reason}"
            )

        required = self.CAPABILITY_PERMISSIONS.get(capability)
        if required is not None:
            granted = set(permissions or ())
            if required not in granted:
                raise PermissionDeniedError(
                    f"capability '{capability}' requires permission "
                    f"'{required.value}', which was not granted"
                )

        logger.info("Executing integration capability '%s' via '%s'", capability, self.name)
        return self._dispatch(capability, dict(params or {}))

    @abstractmethod
    def _capabilities(self) -> tuple[str, ...]:
        """Return the stable capability names this connector supports."""

    @abstractmethod
    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute one supported capability over structured parameters."""

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Return the supported capability names in deterministic order."""
        return tuple(sorted(self._capabilities()))

    def get_capabilities(self) -> tuple[str, ...]:
        """Return the supported capability names (BaseConnector hook)."""
        return self.capabilities

    # ------------------------------------------------------------------
    # Connector lifecycle
    # ------------------------------------------------------------------
    def connect(self) -> None:
        """Connect by validating configuration and reporting health."""
        self._set_health(self.configuration_health())

    def disconnect(self) -> None:
        """Release connector resources and mark disconnected."""
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED))

    def health_check(self) -> ConnectorHealth:
        """Return configuration health without performing network calls."""
        return self.configuration_health()

    @staticmethod
    def _env(name: str) -> str | None:
        """Read one environment variable without raising on absence."""
        import os

        value = os.environ.get(name)
        if value is None or not value.strip():
            return None
        return value.strip()
