"""In-memory sales reporting service and integration placeholders.

This module deliberately contains no transport clients or credentials.  The
hooks provide a stable seam for future WooCommerce, Twenty CRM, and email
connectors without making network requests from the executive runtime.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping

from app.executives.executive_models import (
    ExecutiveAlert,
    ExecutivePriority,
    ExecutiveRecommendation,
)
from app.executives.sales.sales_models import (
    SalesIntegrationHook,
    SalesKPI,
    SalesSummary,
)


class SalesService:
    """Supply deterministic sales data until production connectors are enabled."""

    _INTEGRATIONS = ("woocommerce", "twenty_crm", "email")

    def __init__(self) -> None:
        """Create an uninitialized service with inactive integration hooks."""

        self._initialized = False
        self._integration_hooks = {
            "woocommerce": SalesIntegrationHook(
                executive_name="Sales",
                title="WooCommerce integration",
                description="Placeholder hook for commerce order and revenue data.",
                integration="woocommerce",
            ),
            "twenty_crm": SalesIntegrationHook(
                executive_name="Sales",
                title="Twenty CRM integration",
                description="Placeholder hook for CRM pipeline and deal data.",
                integration="twenty_crm",
            ),
            "email": SalesIntegrationHook(
                executive_name="Sales",
                title="Email integration",
                description="Placeholder hook for sales outreach and follow-up data.",
                integration="email",
            ),
        }

    def initialize(self) -> None:
        """Mark the in-memory service ready; no external integrations are called."""

        self._initialized = True

    def shutdown(self) -> None:
        """Mark the service unavailable and release no external resources."""

        self._initialized = False

    def health_check(self) -> bool:
        """Return whether the local sales service has been initialized."""

        return self._initialized

    def get_summary(self) -> SalesSummary:
        """Return a zero-data baseline while integration hooks are inactive."""

        return SalesSummary(
            executive_name="Sales",
            title="Sales overview",
            description="Live sales data is unavailable until integrations are configured.",
            status="ready" if self._initialized else "not_initialized",
        )

    def get_kpis(self) -> tuple[SalesKPI, ...]:
        """Return the baseline KPI set with explicit zero values."""

        return (
            SalesKPI(title="Revenue", value=0.0, target=0.0, unit="currency"),
            SalesKPI(title="Pipeline value", value=0.0, target=0.0, unit="currency"),
            SalesKPI(title="Win rate", value=0.0, target=0.0, unit="ratio"),
        )

    def get_alerts(self) -> tuple[ExecutiveAlert, ...]:
        """Return active sales alerts; none exist before connectors are configured."""

        return ()

    def get_priorities(self) -> tuple[ExecutivePriority, ...]:
        """Return ranked sales priorities; none are inferred from placeholder data."""

        return ()

    def get_recommendations(self) -> tuple[ExecutiveRecommendation, ...]:
        """Return recommendations; none are generated without live sales data."""

        return ()

    def execute(self, action: str, **kwargs: Any) -> Mapping[str, Any]:
        """Execute a safe local action without calling an external provider.

        ``refresh`` is intentionally a no-op placeholder that lets callers use
        the future refresh contract today.  Reporting actions return the same
        typed data exposed by the public service methods.
        """

        if not isinstance(action, str) or not (normalized_action := action.strip()):
            raise ValueError("action is required")
        if kwargs:
            unsupported_arguments = ", ".join(sorted(kwargs))
            raise ValueError(f"unsupported action arguments: {unsupported_arguments}")

        actions: dict[str, Any] = {
            "summary": self.get_summary,
            "kpis": self.get_kpis,
            "alerts": self.get_alerts,
            "priorities": self.get_priorities,
            "recommendations": self.get_recommendations,
        }
        action_handler = actions.get(normalized_action.casefold())
        if action_handler is not None:
            return {"action": normalized_action, "result": action_handler()}
        if normalized_action.casefold() == "refresh":
            return {
                "action": normalized_action,
                "status": "accepted",
                "message": "Sales refresh is a placeholder; no external API call was made.",
            }
        raise ValueError(f"unsupported sales action: {normalized_action}")

    def supported_integrations(self) -> tuple[str, ...]:
        """Return the stable integration identifiers exposed by this service."""

        return self._INTEGRATIONS

    @property
    def integration_hooks(self) -> Mapping[str, SalesIntegrationHook]:
        """Return immutable metadata for each available integration seam."""

        return MappingProxyType(dict(self._integration_hooks))

    def get_integration_hook(self, integration: str) -> SalesIntegrationHook:
        """Return one named placeholder hook.

        Raises:
            LookupError: If ``integration`` is not a supported integration.
        """

        if not isinstance(integration, str):
            raise LookupError("integration is not supported")
        hook = self._integration_hooks.get(integration.strip().casefold())
        if hook is None:
            raise LookupError(f"integration is not supported: {integration}")
        return hook
