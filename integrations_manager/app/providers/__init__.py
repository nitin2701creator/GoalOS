from integrations_manager.app.providers.base import BaseProvider, IntegrationInfo, TestResult, OAuthConfig
from integrations_manager.app.providers.woocommerce import WooCommerceProvider
from integrations_manager.app.providers.google_analytics import GoogleAnalyticsProvider
from integrations_manager.app.providers.meta import MetaProvider
from integrations_manager.app.providers.linkedin import LinkedInProvider
from integrations_manager.app.providers.twitter import TwitterProvider
from integrations_manager.app.providers.reddit import RedditProvider
from integrations_manager.app.providers.openwa import OpenWAProvider
from integrations_manager.app.providers.wacrm import WacrmProvider
from integrations_manager.app.providers.calling import CallingProvider
from integrations_manager.app.providers.openmontage import OpenMontageProvider

PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    # Communication
    "openwa": OpenWAProvider,
    "wacrm": WacrmProvider,
    "calling": CallingProvider,
    # Content / Media
    "openmontage": OpenMontageProvider,
    # Commerce
    "woocommerce": WooCommerceProvider,
    # Analytics
    "google_analytics": GoogleAnalyticsProvider,
    # Social
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
    "CallingProvider",
    "OpenMontageProvider",
    "GoogleAnalyticsProvider",
    "LinkedInProvider",
    "MetaProvider",
    "OpenWAProvider",
    "RedditProvider",
    "TwitterProvider",
    "WacrmProvider",
    "WooCommerceProvider",
]
