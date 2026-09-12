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
from app.integrations.external.crawl4ai import Crawl4AIConnector
from app.integrations.external.memory import MemoryConnector
from app.integrations.external.searxng import SearXNGConnector
from app.integrations.external.calling import CallingConnector
from app.integrations.external.whatsapp import OpenWAConnector, WacrmConnector
from app.integrations.google_analytics import GoogleAnalyticsConnector
from app.integrations.google_calendar import GoogleCalendarConnector
from app.integrations.google_drive import GoogleDriveConnector
from app.integrations.http_client import HttpClient
from app.integrations.integration_connector import IntegrationConnector
from app.integrations.linkedin import LinkedInConnector
from app.integrations.meta_ads import MetaAdsConnector
from app.integrations.meta_social import MetaSocialConnector
from app.integrations.n8n import N8NConnector
from app.integrations.reddit import RedditConnector
from app.integrations.scheduler import SchedulerConnector
from app.integrations.social import SocialConnector
from app.integrations.twenty import TwentyConnector
from app.integrations.x_twitter import TwitterConnector
from app.integrations.web import DuckDuckGoSearchProvider, WebConnector
from app.integrations.website import WebsiteConnector
from app.integrations.woocommerce import WooCommerceConnector

#: Canonical integration names agents/skills can declare.
SUPPORTED_INTEGRATIONS: tuple[str, ...] = (
    "web",
    "website",
    "gmail",
    "calendar",
    "drive",
    "woocommerce",
    "google_analytics",
    "meta_ads",
    "meta_social",
    "scheduler",
    "twenty",
    "linkedin",
    "social",
    "n8n",
    "reddit",
    "twitter",
    "whatsapp",
    "wacrm",
    "calling",
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

#: Standard connectors constructed as ``ConnectorClass(client=client)`` that
#: should be registered automatically in every default composition root.
#: Adding a new integration to this tuple (plus ``SUPPORTED_INTEGRATIONS``
#: and ``INTEGRATION_TYPES``) is the entire wiring it needs — no other
#: registration code is required. Registration is deterministic: the class
#: is always the same, never discovered by scanning the filesystem or by
#: importing arbitrary modules at runtime.
AUTO_CLIENT_CONNECTORS: tuple[type[IntegrationConnector], ...] = (
    GoogleAnalyticsConnector,
    GoogleCalendarConnector,
    GoogleDriveConnector,
    MetaAdsConnector,
    MetaSocialConnector,
    N8NConnector,
    RedditConnector,
    TwentyConnector,
    LinkedInConnector,
    TwitterConnector,
    WooCommerceConnector,
)

#: External capability adapters constructed with no arguments and registered
#: automatically in every default composition root.
AUTO_NOARG_CONNECTORS: tuple[type[IntegrationConnector], ...] = (
    OpenWAConnector,
    WacrmConnector,
    CallingConnector,
    MemoryConnector,
    Crawl4AIConnector,
    SearXNGConnector,
)

#: Registry name → functional integration type (web, email, calendar,
#: storage, crm, ...). Used by the persisted integration registry so
#: every registered connector is represented as an executable integration
#: with a type.
INTEGRATION_TYPES: dict[str, str] = {
    "web": "web",
    "website": "web",
    "gmail": "email",
    "calendar": "calendar",
    "drive": "storage",
    "woocommerce": "commerce",
    "google_analytics": "analytics",
    "meta_ads": "advertising",
    "meta_social": "social",
    "scheduler": "scheduler",
    "twenty": "crm",
    "linkedin": "social",
    "social": "social",
    "n8n": "automation",
    "reddit": "social",
    "twitter": "social",
    "whatsapp": "communication",
    "wacrm": "communication",
    "calling": "communication",
}


def integration_type_for(name: str) -> str:
    """Return the functional type for a registered integration name."""
    return INTEGRATION_TYPES.get(name.strip(), "integration")


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

    # Auto-registration: every standard connector created from a shared
    # HttpClient, plus the no-argument external adapters.
    for connector_cls in AUTO_CLIENT_CONNECTORS:
        registry.register(connector_cls(client=client or HttpClient()))
    for connector_cls in AUTO_NOARG_CONNECTORS:
        registry.register(connector_cls())

    # Connectors with explicit composition (shared services, DB access).
    registry.register(GmailProvider(service=_default_gmail_service(client)))
    registry.register(SchedulerConnector(db=session))

    meta_social = registry.get_connector("meta_social")
    twitter_connector = registry.get_connector("twitter")
    reddit_connector = registry.get_connector("reddit")
    social = SocialConnector()
    social.register_provider("meta", meta_social)
    social.register_provider("linkedin", registry.get_connector("linkedin"))
    social.register_provider("x", twitter_connector)
    social.register_provider("reddit", reddit_connector)
    registry.register(social)

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
