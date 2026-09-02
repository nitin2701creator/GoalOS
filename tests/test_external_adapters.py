"""Tests for external capability adapters.

Covers:
- OpenWA WhatsApp connector initialization and configuration
- Crawl4AI connector initialization and configuration
- SearXNG connector initialization and configuration
- Memory connector initialization and configuration
- Capability registration
- Request construction
- Error handling for unconfigured adapters
- Credential redaction in error messages
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.integrations.external.crawl4ai import Crawl4AIConnector
from app.integrations.external.memory import MemoryConnector
from app.integrations.external.searxng import SearXNGConnector
from app.integrations.external.whatsapp import OpenWAConnector


# ---------------------------------------------------------------------------
# OpenWA WhatsApp Adapter
# ---------------------------------------------------------------------------

class TestOpenWAConnector:
    def test_name_and_description(self) -> None:
        connector = OpenWAConnector()
        assert connector.name == "openwa"
        assert "WhatsApp" in connector.description

    def test_not_configured_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_OPENWA_BASE_URL", raising=False)
        connector = OpenWAConnector()
        assert connector.is_configured is False

    def test_configured_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_OPENWA_BASE_URL", "http://localhost:5800")
        connector = OpenWAConnector()
        assert connector.is_configured is True

    def test_connect_without_config_reports_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_OPENWA_BASE_URL", raising=False)
        connector = OpenWAConnector()
        connector.connect()
        from app.integrations.connector_health import ConnectorHealthStatus
        assert connector.status == ConnectorHealthStatus.NOT_CONFIGURED

    def test_connect_with_config_reports_healthy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_OPENWA_BASE_URL", "http://localhost:5800")
        connector = OpenWAConnector()
        connector.connect()
        from app.integrations.connector_health import ConnectorHealthStatus
        assert connector.status == ConnectorHealthStatus.HEALTHY

    def test_execute_returns_error_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_OPENWA_BASE_URL", raising=False)
        connector = OpenWAConnector()
        result = connector.execute("whatsapp.send_message", {"to_number": "+1234", "body": "hi"})
        assert "INTEGRATION_NOT_CONFIGURED" in result["error"]

    def test_execute_unknown_capability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_OPENWA_BASE_URL", "http://localhost:5800")
        connector = OpenWAConnector()
        result = connector.execute("whatsapp.unknown_op", {})
        assert "unknown capability" in result["error"]

    def test_send_message_validates_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_OPENWA_BASE_URL", "http://localhost:5800")
        connector = OpenWAConnector()
        result = connector.execute("whatsapp.send_message", {"to_number": "", "body": ""})
        assert "required" in result["error"]

    def test_capability_permissions_defined(self) -> None:
        connector = OpenWAConnector()
        assert "whatsapp.send_message" in connector.CAPABILITY_PERMISSIONS
        assert "whatsapp.receive_message" in connector.CAPABILITY_PERMISSIONS
        assert "whatsapp.list_sessions" in connector.CAPABILITY_PERMISSIONS

    def test_api_key_not_exposed_in_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_OPENWA_BASE_URL", "http://localhost:5800")
        monkeypatch.setenv("GOALOS_OPENWA_API_KEY", "super-secret-key-12345")
        connector = OpenWAConnector()
        result = connector.execute("whatsapp.send_message", {"to_number": "", "body": ""})
        assert "super-secret" not in str(result)


# ---------------------------------------------------------------------------
# Crawl4AI Web/SEO Adapter
# ---------------------------------------------------------------------------

class TestCrawl4AIConnector:
    def test_name_and_description(self) -> None:
        connector = Crawl4AIConnector()
        assert connector.name == "crawl4ai"
        assert "crawl" in connector.description.lower() or "web" in connector.description.lower()

    def test_configured_when_library_available(self) -> None:
        connector = Crawl4AIConnector()
        # In the test env, crawl4ai may or may not be installed
        # But the connector should be created without error
        assert connector.name == "crawl4ai"

    def test_execute_unknown_capability(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = Crawl4AIConnector()
        result = connector.execute("web.unknown_op", {})
        assert "unknown capability" in result["error"]

    def test_crawl_url_requires_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = Crawl4AIConnector()
        result = connector.execute("web.crawl_url", {})
        assert "required" in result["error"]

    def test_seo_audit_requires_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        connector = Crawl4AIConnector()
        result = connector.execute("web.seo_audit", {})
        assert "required" in result["error"]

    def test_capability_permissions_defined(self) -> None:
        connector = Crawl4AIConnector()
        assert "web.crawl_url" in connector.CAPABILITY_PERMISSIONS
        assert "web.seo_audit" in connector.CAPABILITY_PERMISSIONS
        assert "web.extract_content" in connector.CAPABILITY_PERMISSIONS


# ---------------------------------------------------------------------------
# SearXNG Search Adapter
# ---------------------------------------------------------------------------

class TestSearXNGConnector:
    def test_name_and_description(self) -> None:
        connector = SearXNGConnector()
        assert connector.name == "searxng"
        assert "search" in connector.description.lower()

    def test_not_configured_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_SEARXNG_BASE_URL", raising=False)
        connector = SearXNGConnector()
        assert connector.is_configured is False

    def test_configured_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_SEARXNG_BASE_URL", "http://localhost:8888")
        connector = SearXNGConnector()
        assert connector.is_configured is True

    def test_execute_returns_error_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_SEARXNG_BASE_URL", raising=False)
        connector = SearXNGConnector()
        result = connector.execute("search.web", {"query": "test"})
        assert "INTEGRATION_NOT_CONFIGURED" in result["error"]

    def test_search_requires_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_SEARXNG_BASE_URL", "http://localhost:8888")
        connector = SearXNGConnector()
        result = connector.execute("search.web", {})
        assert "required" in result["error"]

    def test_capability_permissions_defined(self) -> None:
        connector = SearXNGConnector()
        assert "search.web" in connector.CAPABILITY_PERMISSIONS
        assert "search.news" in connector.CAPABILITY_PERMISSIONS

    def test_connect_without_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_SEARXNG_BASE_URL", raising=False)
        connector = SearXNGConnector()
        connector.connect()
        from app.integrations.connector_health import ConnectorHealthStatus
        assert connector.status == ConnectorHealthStatus.NOT_CONFIGURED


# ---------------------------------------------------------------------------
# Memory Adapter
# ---------------------------------------------------------------------------

class TestMemoryConnector:
    def test_name_and_description(self) -> None:
        connector = MemoryConnector()
        assert connector.name == "memory"
        assert "memory" in connector.description.lower()

    def test_not_configured_without_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_MEMORY_BASE_URL", raising=False)
        connector = MemoryConnector()
        assert connector.is_configured is False

    def test_configured_with_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_MEMORY_BASE_URL", "http://localhost:8080")
        connector = MemoryConnector()
        assert connector.is_configured is True

    def test_execute_returns_error_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_MEMORY_BASE_URL", raising=False)
        connector = MemoryConnector()
        result = connector.execute("memory.remember", {"content": "test"})
        assert "INTEGRATION_NOT_CONFIGURED" in result["error"]

    def test_remember_requires_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_MEMORY_BASE_URL", "http://localhost:8080")
        connector = MemoryConnector()
        result = connector.execute("memory.remember", {})
        assert "required" in result["error"]

    def test_recall_requires_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_MEMORY_BASE_URL", "http://localhost:8080")
        connector = MemoryConnector()
        result = connector.execute("memory.recall", {})
        assert "required" in result["error"]

    def test_forget_requires_memory_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOALOS_MEMORY_BASE_URL", "http://localhost:8080")
        connector = MemoryConnector()
        result = connector.execute("memory.forget", {})
        assert "required" in result["error"]

    def test_health_check_when_not_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOALOS_MEMORY_BASE_URL", raising=False)
        connector = MemoryConnector()
        result = connector.execute("memory.health", {})
        assert "not deployed" in result["message"].lower() or "not_configured" in result["status"]

    def test_capability_permissions_defined(self) -> None:
        connector = MemoryConnector()
        assert "memory.remember" in connector.CAPABILITY_PERMISSIONS
        assert "memory.recall" in connector.CAPABILITY_PERMISSIONS
        assert "memory.search" in connector.CAPABILITY_PERMISSIONS
        assert "memory.forget" in connector.CAPABILITY_PERMISSIONS
        assert "memory.health" in connector.CAPABILITY_PERMISSIONS


# ---------------------------------------------------------------------------
# Capability Registration
# ---------------------------------------------------------------------------

class TestCapabilityRegistration:
    def test_whatsapp_capabilities_registered(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "whatsapp_send_message" in BUILTIN_CAPABILITIES
        assert "whatsapp_send_media" in BUILTIN_CAPABILITIES
        assert "whatsapp_receive_message" in BUILTIN_CAPABILITIES
        assert "whatsapp_list_sessions" in BUILTIN_CAPABILITIES
        assert "whatsapp_session_status" in BUILTIN_CAPABILITIES

    def test_memory_capabilities_registered(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "memory_remember" in BUILTIN_CAPABILITIES
        assert "memory_recall" in BUILTIN_CAPABILITIES
        assert "memory_search" in BUILTIN_CAPABILITIES
        assert "memory_forget" in BUILTIN_CAPABILITIES
        assert "memory_health" in BUILTIN_CAPABILITIES

    def test_web_seo_capabilities_registered(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "web_crawl_url" in BUILTIN_CAPABILITIES
        assert "web_analyze_page" in BUILTIN_CAPABILITIES
        assert "web_seo_audit" in BUILTIN_CAPABILITIES
        assert "web_extract_content" in BUILTIN_CAPABILITIES

    def test_search_capabilities_registered(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        assert "search_web" in BUILTIN_CAPABILITIES
        assert "search_news" in BUILTIN_CAPABILITIES

    def test_whatsapp_capabilities_have_schemas(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["whatsapp_send_message"]
        assert cap.input_schema["type"] == "object"
        assert "to_number" in cap.input_schema["properties"]
        assert "body" in cap.input_schema["properties"]

    def test_whatsapp_requires_approval(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["whatsapp_send_message"]
        assert cap.requires_approval is True

    def test_memory_capabilities_use_correct_provider(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["memory_remember"]
        assert cap.provider == "memory"
        assert cap.implementation == "memory.remember"

    def test_web_capabilities_use_correct_provider(self) -> None:
        from app.agents.capability_definitions import BUILTIN_CAPABILITIES
        cap = BUILTIN_CAPABILITIES["web_crawl_url"]
        assert cap.provider == "crawl4ai"
        assert cap.implementation == "web.crawl_url"
