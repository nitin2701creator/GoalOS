from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.providers.woocommerce import WooCommerceProvider
from integrations_manager.app.providers.google_analytics import GoogleAnalyticsProvider
from integrations_manager.app.providers.meta import MetaProvider
from integrations_manager.app.providers.linkedin import LinkedInProvider
from integrations_manager.app.providers.twitter import TwitterProvider
from integrations_manager.app.providers.reddit import RedditProvider

PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "woocommerce": WooCommerceProvider,
    "google_analytics": GoogleAnalyticsProvider,
    "meta": MetaProvider,
    "linkedin": LinkedInProvider,
    "twitter": TwitterProvider,
    "reddit": RedditProvider,
}

__all__ = [
    "BaseProvider",
    "IntegrationInfo",
    "TestResult",
    "OAuthConfig",
    "PROVIDER_REGISTRY",
    "WooCommerceProvider",
    "GoogleAnalyticsProvider",
    "MetaProvider",
    "LinkedInProvider",
    "TwitterProvider",
    "RedditProvider",
]
