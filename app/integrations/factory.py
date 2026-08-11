"""Composition root for GoalOS integration connectors.

``build_default_registry`` wires every connector from environment
configuration (via ``.env`` / the deployment's secret manager). The
application starts with whatever is configured; unconfigured connectors
report ``Not Configured`` honestly. Inject ``client``/``session`` to
override transports for hermetic tests.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.email.providers.gmail_provider import GmailProvider
from app.integrations.google_analytics import GoogleAnalyticsConnector
from app.integrations.http_client import HttpClient
from app.integrations.meta_ads import MetaAdsConnector
from app.integrations.scheduler import SchedulerConnector
from app.integrations.web import DuckDuckGoSearchProvider, WebConnector
from app.integrations.website import WebsiteConnector
from app.integrations.woocommerce import WooCommerceConnector

#: Canonical integration names agents/skills can declare.
SUPPORTED_INTEGRATIONS: tuple[str, ...] = (
    "web",
    "website",
    "gmail",
    "woocommerce",
    "google_analytics",
    "meta_ads",
    "scheduler",
)

#: Capability-prefix → registry-name aliases. Connector capability names
#: use short prefixes (``email.*``, ``analytics.*``, ``meta.*``) while the
#: registry keys them under their full names (``gmail``,
#: ``google_analytics``, ``meta_ads``).
_CAPABILITY_INTEGRATION_ALIASES: dict[str, str] = {
    "email": "gmail",
    "analytics": "google_analytics",
    "meta": "meta_ads",
}


def integration_for_capability(capability_name: str) -> str:
    """Map a ``system.action`` capability to its registry integration name."""
    prefix, _, _ = capability_name.partition(".")
    return _CAPABILITY_INTEGRATION_ALIASES.get(prefix, prefix)


def build_default_registry(
    session: Session | None = None,
    client: HttpClient | None = None,
    *,
    with_search: bool = True,
) -> ConnectorRegistry:
    """Build and register every connector for one runtime composition root.

    Args:
        session: Database session (required for the scheduler connector).
        client: Shared HTTP client override (tests inject a fake opener).
        with_search: Whether to attach the configured search provider to
            the web connector.

    Returns:
        A populated :class:`ConnectorRegistry`.
    """
    registry = ConnectorRegistry()

    search_provider = None
    if with_search:
        provider_name = WebConnector._env("GOALOS_SEARCH_PROVIDER")
        if provider_name and provider_name.strip().casefold() == "duckduckgo":
            search_provider = DuckDuckGoSearchProvider(client=client or HttpClient())
    registry.register(WebConnector(client=client or HttpClient(), search_provider=search_provider))
    registry.register(WebsiteConnector(web=WebConnector(client=client or HttpClient())))
    registry.register(WooCommerceConnector(client=client or HttpClient()))
    registry.register(
        GoogleAnalyticsConnector(client=client or HttpClient())
    )
    registry.register(MetaAdsConnector(client=client or HttpClient()))
    registry.register(GmailProvider(service=_default_gmail_service(client)))
    registry.register(SchedulerConnector(db=session))
    return registry


def _default_gmail_service(client: HttpClient | None) -> object:
    """Return a configured Gmail REST service or the unavailable default."""
    from app.integrations.email.providers.gmail_provider import UnavailableGmailService
    from app.integrations.email.providers.gmail_rest_service import (
        GmailRESTService,
        GmailTokenProvider,
    )

    service = GmailRESTService(
        client=client or HttpClient(),
        token_provider=GmailTokenProvider(client=client or HttpClient()),
    )
    if service.is_configured:
        return service
    return UnavailableGmailService()
