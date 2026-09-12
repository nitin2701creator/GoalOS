"""Tests for integration providers — info, fields, OAuth config, masking."""
import os
import secrets
import pytest

os.environ["IM_ENCRYPTION_KEY"] = secrets.token_hex(32)
os.environ["IM_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["IM_ADMIN_PASSWORD"] = "test"

from integrations_manager.app.providers import PROVIDER_REGISTRY
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


class TestProviderRegistry:
    def test_all_providers_registered(self):
        expected = {
            "woocommerce", "google_analytics", "google_calendar", "google_drive",
            "meta", "linkedin", "twitter", "reddit",
            "openwa", "wacrm", "calling", "openmontage",
        }
        assert set(PROVIDER_REGISTRY.keys()) == expected

    def test_all_providers_are_subclasses(self):
        for slug, cls in PROVIDER_REGISTRY.items():
            assert issubclass(cls, BaseProvider), f"{slug} is not a BaseProvider subclass"

    def test_all_providers_instantiate(self):
        for slug, cls in PROVIDER_REGISTRY.items():
            provider = cls()
            assert provider is not None


class TestProviderInfo:
    @pytest.mark.parametrize("slug,expected_name", [
        ("woocommerce", "WooCommerce"),
        ("google_analytics", "Google Analytics 4"),
        ("google_calendar", "Google Calendar"),
        ("google_drive", "Google Drive"),
        ("meta", "Meta / Facebook"),
        ("linkedin", "LinkedIn"),
        ("twitter", "X / Twitter"),
        ("reddit", "Reddit"),
        ("openwa", "WhatsApp / OpenWA"),
        ("wacrm", "WhatsApp / WACRM"),
        ("calling", "Calling / Telephony"),
        ("openmontage", "Video Production / OpenMontage"),
    ])
    def test_info_returns_correct_name(self, slug, expected_name):
        provider = PROVIDER_REGISTRY[slug]()
        info = provider.info()
        assert info.name == expected_name
        assert info.slug == slug
        assert info.auth_type in ("api_key", "oauth2")
        assert len(info.icon) > 0

    @pytest.mark.parametrize("slug", PROVIDER_REGISTRY.keys())
    def test_credential_fields_not_empty_for_api_key(self, slug):
        provider = PROVIDER_REGISTRY[slug]()
        fields = provider.get_credential_fields()
        if provider.info().auth_type == "api_key":
            assert len(fields) > 0, f"{slug} (api_key) has no credential fields"
        for f in fields:
            assert "key" in f
            assert "label" in f
            assert "type" in f


class TestOAuthConfig:
    def test_oauth_providers_have_config(self):
        for slug in ["google_analytics", "meta", "linkedin", "reddit", "twitter"]:
            provider = PROVIDER_REGISTRY[slug]()
            config = provider.get_oauth_config()
            assert config is not None, f"{slug} should have OAuth config"
            assert config.auth_url.startswith("https://")
            assert config.token_url.startswith("https://")
            assert len(config.scopes) > 0
            assert config.redirect_uri

    def test_woocommerce_no_oauth(self):
        provider = WooCommerceProvider()
        assert provider.get_oauth_config() is None


class TestCredentialMasking:
    def test_mask_long_value(self):
        provider = WooCommerceProvider()
        masked = provider.mask_value("key", "abcdefghijklmnopqrstuvwxyz")
        assert masked.startswith("abcd")
        assert masked.endswith("wxyz")
        assert "•" in masked
        assert len(masked) == len("abcdefghijklmnopqrstuvwxyz")

    def test_mask_short_value(self):
        provider = WooCommerceProvider()
        masked = provider.mask_value("key", "abc")
        assert masked == "•••"

    def test_mask_empty(self):
        provider = WooCommerceProvider()
        assert provider.mask_value("key", "") == ""

    def test_mask_exactly_8_chars(self):
        provider = WooCommerceProvider()
        masked = provider.mask_value("key", "12345678")
        # 8 chars: first 4 + 0 dots + last 4 = same string
        assert masked == "12345678"


class TestProviderTestConnection:
    @pytest.mark.asyncio
    async def test_woocommerce_missing_creds(self):
        provider = WooCommerceProvider()
        result = await provider.test_connection({})
        assert result.success is False
        assert "Missing" in result.message

    @pytest.mark.asyncio
    async def test_ga4_no_token(self):
        provider = GoogleAnalyticsProvider()
        result = await provider.test_connection({})
        assert result.success is False
        assert "Not authenticated" in result.message

    @pytest.mark.asyncio
    async def test_meta_no_token(self):
        provider = MetaProvider()
        result = await provider.test_connection({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_linkedin_no_token(self):
        provider = LinkedInProvider()
        result = await provider.test_connection({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_twitter_no_token(self):
        provider = TwitterProvider()
        result = await provider.test_connection({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reddit_no_token(self):
        provider = RedditProvider()
        result = await provider.test_connection({})
        assert result.success is False

    @pytest.mark.asyncio
    async def test_get_account_info_no_token(self):
        for slug in ["google_analytics", "meta", "linkedin", "twitter", "reddit"]:
            provider = PROVIDER_REGISTRY[slug]()
            info = await provider.get_account_info({})
            assert "error" in info

    @pytest.mark.asyncio
    async def test_openwa_no_base_url(self):
        provider = OpenWAProvider()
        result = await provider.test_connection({})
        assert result.success is False
        assert "Base URL" in result.message

    @pytest.mark.asyncio
    async def test_wacrm_no_base_url(self):
        provider = WacrmProvider()
        result = await provider.test_connection({})
        assert result.success is False
        assert "Base URL" in result.message

    @pytest.mark.asyncio
    async def test_wacrm_no_api_key(self):
        provider = WacrmProvider()
        result = await provider.test_connection({"base_url": "http://localhost:3000"})
        assert result.success is False
        assert "API key" in result.message

    @pytest.mark.asyncio
    async def test_calling_no_base_url(self):
        provider = CallingProvider()
        result = await provider.test_connection({})
        assert result.success is False
        assert "No telephony provider" in result.message

    @pytest.mark.asyncio
    async def test_openmontage_no_path(self):
        provider = OpenMontageProvider()
        result = await provider.test_connection({})
        assert result.success is False
        assert "Installation path" in result.message

    @pytest.mark.asyncio
    async def test_openmontage_no_oauth(self):
        provider = OpenMontageProvider()
        assert provider.get_oauth_config() is None

    @pytest.mark.asyncio
    async def test_openwa_no_oauth(self):
        provider = OpenWAProvider()
        assert provider.get_oauth_config() is None

    @pytest.mark.asyncio
    async def test_wacrm_no_oauth(self):
        provider = WacrmProvider()
        assert provider.get_oauth_config() is None

    @pytest.mark.asyncio
    async def test_calling_no_oauth(self):
        provider = CallingProvider()
        assert provider.get_oauth_config() is None


SYSTEM_STATUS_OK = {
    "environment": {
        "woocommerce_version": "9.1.0",
        "wp_version": "6.7",
        "site_url": "http://www.organigram.in",
    }
}


class TestWooCommerceConnection:
    PROVIDER_CREDS = {
        "store_url": "http://www.organigram.in",
        "consumer_key": "ck-test",
        "consumer_secret": "cs-test",
    }

    @staticmethod
    def _mocked_urlopen(*, body=None, status_error=None, connection_error=None):
        """Patch the provider's urlopen and assert no secrets in the query string."""
        import json as _json

        from integrations_manager.app.providers import woocommerce as woo_module
        from urllib.parse import urlsplit

        calls = []

        def fake_urlopen(request, timeout=None):
            url = str(getattr(request, "full_url", request))
            calls.append(url)
            query = urlsplit(url).query
            assert "consumer_key" not in query and "consumer_secret" not in query, (
                "credentials must never be sent in the query string"
            )
            headers = dict(getattr(request, "headers", {}) or {})
            assert headers.get("Authorization", "").startswith("Basic "), (
                "credentials must be sent via the Authorization header"
            )
            if status_error is not None:
                raise status_error
            if connection_error is not None:
                raise connection_error
            if body is None:
                raise AssertionError("no body configured for mock urlopen")

            class _Resp:
                def __exit__(self, *args):
                    return False

                def __enter__(self):
                    return self

                def read(self):
                    return body if isinstance(body, bytes) else str(body).encode()

            return _Resp()

        woo_module.urlopen = fake_urlopen
        return calls

    @pytest.mark.asyncio
    async def test_connected_reports_real_api_success(self):
        import json as _json

        calls = self._mocked_urlopen(body=_json.dumps(SYSTEM_STATUS_OK))

        provider = WooCommerceProvider()
        result = await provider.test_connection(self.PROVIDER_CREDS)

        assert result.success is True
        assert result.status == "connected"
        assert result.details["wc_version"] == "9.1.0"
        assert len(calls) == 1
        assert calls[0] == "http://www.organigram.in/wp-json/wc/v3/system_status"

    @pytest.mark.asyncio
    async def test_auth_failure_is_distinct(self):
        from urllib.error import HTTPError

        self._mocked_urlopen(status_error=HTTPError("http://x", 401, "Unauthorized", {}, None))

        provider = WooCommerceProvider()
        result = await provider.test_connection(self.PROVIDER_CREDS)

        assert result.success is False
        assert result.status == "auth_failed"
        assert "Consumer Key" in result.message

    @pytest.mark.asyncio
    async def test_credentials_sent_via_header_not_query_string(self):
        import json as _json

        self._mocked_urlopen(body=_json.dumps(SYSTEM_STATUS_OK))

        provider = WooCommerceProvider()
        await provider.test_connection(self.PROVIDER_CREDS)

    @pytest.mark.asyncio
    async def test_unreachable_classifies_dns_and_network_failures(self):
        from urllib.error import URLError
        from socket import gaierror

        self._mocked_urlopen(connection_error=URLError(gaierror(-2, "Name or service not known")))

        provider = WooCommerceProvider()
        result = await provider.test_connection(self.PROVIDER_CREDS)

        assert result.success is False
        assert result.status == "unreachable"

    @pytest.mark.asyncio
    async def test_timeout_classifies_as_unreachable(self):
        def timeout(request, timeout=None):
            import socket
            import time
            raise TimeoutError("timed out")

        from integrations_manager.app.providers import woocommerce as woo_module
        woo_module.urlopen = timeout

        provider = WooCommerceProvider()
        result = await provider.test_connection(self.PROVIDER_CREDS)

        assert result.success is False
        assert result.status == "unreachable"

    @pytest.mark.asyncio
    async def test_not_a_woocommerce_store(self):
        self._mocked_urlopen(body="<html><body>WordPress home page</body></html>")

        provider = WooCommerceProvider()
        result = await provider.test_connection(self.PROVIDER_CREDS)

        assert result.success is False
        assert result.status == "api_unavailable"

    @pytest.mark.asyncio
    async def test_malformed_json_classifies_as_api_unavailable(self):
        self._mocked_urlopen(body="this is not json")

        provider = WooCommerceProvider()
        result = await provider.test_connection(self.PROVIDER_CREDS)

        assert result.success is False
        assert result.status == "api_unavailable"

    @pytest.mark.asyncio
    async def test_invalid_url_is_invalid_config(self):
        provider = WooCommerceProvider()
        result = await provider.test_connection({**self.PROVIDER_CREDS, "store_url": "ftp://not-valid"})
        assert result.success is False
        assert result.status == "invalid_config"

    @pytest.mark.asyncio
    async def test_embedded_credentials_rejected(self):
        provider = WooCommerceProvider()
        result = await provider.test_connection({**self.PROVIDER_CREDS, "store_url": "https://user:pass@example.com"})
        assert result.success is False
        assert result.status == "invalid_config"
        assert "credentials" in result.message.lower()

    @pytest.mark.asyncio
    async def test_www_and_apex_fallback_on_dns_failure(self):
        import json as _json
        from urllib.error import URLError
        from socket import gaierror

        from urllib.request import Request as _Request
        from integrations_manager.app.providers import woocommerce as woo_module

        original_open = woo_module.urlopen
        calls = []

        def fake_urlopen(request, timeout=None):
            url = str(getattr(request, "full_url", request))
            calls.append(url)
            if "www.organigram.in" in url:
                raise URLError(gaierror(-2, "Name or service not known"))

            class _Resp:
                def __exit__(self, *args):
                    return False

                def __enter__(self):
                    return self

                def read(self):
                    return _json.dumps(SYSTEM_STATUS_OK).encode()

            return _Resp()

        woo_module.urlopen = fake_urlopen
        try:
            provider = WooCommerceProvider()
            result = await provider.test_connection(self.PROVIDER_CREDS)
        finally:
            woo_module.urlopen = original_open

        assert result.success is True
        assert any("organigram.in" in c and "www." not in c for c in calls)

    @pytest.mark.asyncio
    async def test_missing_creds_is_invalid_config(self):
        provider = WooCommerceProvider()
        result = await provider.test_connection({"store_url": "https://shop.example.com"})
        assert result.success is False
        assert result.status == "invalid_config"
        assert "Missing" in result.message

    def test_get_connection_state(self):
        provider = WooCommerceProvider()
        assert provider.get_connection_state({}) == "not_configured"
        assert provider.get_connection_state({"store_url": "https://x.com"}) == "not_configured"
        assert provider.get_connection_state(self.PROVIDER_CREDS) == "configured"
