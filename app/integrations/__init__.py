"""Universal integration framework for GoalOS connectors."""

from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus
from app.integrations.connector_loader import ConnectorLoader
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConfigurationError,
    ConnectionError,
    ConnectorError,
    ConnectorUnavailableError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.factory import SUPPORTED_INTEGRATIONS, build_default_registry
from app.integrations.google_analytics import GoogleAnalyticsConnector
from app.integrations.google_calendar import GoogleCalendarConnector
from app.integrations.google_drive import GoogleDriveConnector
from app.integrations.http_client import (
    HttpClient,
    HttpConnectionError,
    HttpResponse,
    HttpResponseTooLargeError,
    HttpStatusError,
    HttpTimeoutError,
)
from app.integrations.integration_connector import IntegrationConnector
from app.integrations.linkedin import LinkedInConnector
from app.integrations.meta_ads import MetaAdsConnector
from app.integrations.scheduler import SchedulerConnector
from app.integrations.social import SocialConnector
from app.integrations.twenty import TwentyConnector
from app.integrations.web import WebConnector
from app.integrations.website import WebsiteConnector
from app.integrations.woocommerce import WooCommerceConnector

__all__ = [
    "SUPPORTED_INTEGRATIONS",
    "AuthenticationError",
    "BaseConnector",
    "CapabilityUnavailableError",
    "ConfigurationError",
    "ConnectionError",
    "ConnectorError",
    "ConnectorHealth",
    "ConnectorHealthStatus",
    "ConnectorLoader",
    "ConnectorRegistry",
    "ConnectorUnavailableError",
    "GoogleAnalyticsConnector",
    "GoogleCalendarConnector",
    "GoogleDriveConnector",
    "HttpClient",
    "HttpConnectionError",
    "HttpResponse",
    "HttpResponseTooLargeError",
    "HttpStatusError",
    "HttpTimeoutError",
    "IntegrationConnector",
    "LinkedInConnector",
    "MetaAdsConnector",
    "PermissionDeniedError",
    "RateLimitError",
    "SchedulerConnector",
    "SocialConnector",
    "TwentyConnector",
    "WebConnector",
    "WebsiteConnector",
    "WooCommerceConnector",
    "build_default_registry",
]
