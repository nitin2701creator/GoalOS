"""Web/SEO capability adapter — wraps Crawl4AI behind GoalOS interfaces.

Crawl4AI is an LLM-friendly web crawler. This adapter imports it as a
Python library (when available) and falls back to an HTTP client when
the crawl4ai server is running separately.

Environment variables:
    GOALOS_CRAWL4AI_BASE_URL — Optional crawl4ai server URL for remote mode.
                               When empty, uses the Python library directly.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from app.agents.permissions import Permission
from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency at module load
_crawl4ai_available = False
try:
    import crawl4ai  # noqa: F401
    _crawl4ai_available = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class CrawlRequest:
    """Request to crawl a URL."""

    url: str
    max_depth: int = 0
    extract_images: bool = False
    extract_links: bool = True
    js_code: str | None = None
    wait_for: str | None = None


@dataclass(frozen=True, slots=True)
class CrawlResult:
    """Result from crawling a URL."""

    url: str
    title: str
    markdown: str
    html: str = ""
    links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SEOAuditResult:
    """SEO audit result."""

    url: str
    title: str | None = None
    meta_description: str | None = None
    h1_tags: list[str] = field(default_factory=list)
    h2_tags: list[str] = field(default_factory=list)
    internal_links: int = 0
    external_links: int = 0
    images_without_alt: int = 0
    word_count: int = 0
    issues: list[str] = field(default_factory=list)
    score: int = 0


# ---------------------------------------------------------------------------
# Crawl4AI Connector
# ---------------------------------------------------------------------------

class Crawl4AIConnector(BaseConnector):
    """GoalOS connector for web crawling and SEO analysis.

    Supports two modes:
    1. In-process: imports crawl4ai as a Python library (lightweight, no server).
    2. Remote: connects to a crawl4ai server via HTTP.
    """

    required_env_vars: tuple[str, ...] = ()

    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "web.search": Permission.READ_WEBSITE,
        "web.crawl_url": Permission.READ_WEBSITE,
        "web.analyze_page": Permission.READ_WEBSITE,
        "web.seo_audit": Permission.READ_WEBSITE,
        "web.extract_content": Permission.READ_WEBSITE,
    }

    def __init__(self) -> None:
        super().__init__(
            name="crawl4ai",
            description="Crawl4AI web crawler and SEO analysis adapter",
        )

    def get_capabilities(self) -> tuple[str, ...]:
        return tuple(self.CAPABILITY_PERMISSIONS.keys())

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self.CAPABILITY_PERMISSIONS.keys())

    def capability_available(self, capability: str) -> tuple[bool, str]:
        if capability not in self.capabilities:
            return False, f"capability '{capability}' is not supported"
        if not self.is_configured:
            return False, "crawl4ai not available — install crawl4ai or set GOALOS_CRAWL4AI_BASE_URL"
        return True, "available"

    @property
    def server_url(self) -> str:
        return os.environ.get("GOALOS_CRAWL4AI_BASE_URL", "").rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.server_url) or _crawl4ai_available

    # -- Lifecycle --

    def connect(self) -> None:
        if _crawl4ai_available:
            self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY, "crawl4ai library available"))
        elif self.server_url:
            self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY, "crawl4ai server configured"))
        else:
            self._set_health(ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "crawl4ai not installed and GOALOS_CRAWL4AI_BASE_URL not set",
            ))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "disconnected"))

    def health_check(self) -> ConnectorHealth:
        if _crawl4ai_available:
            return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "library mode")
        if self.server_url:
            return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "server mode")
        return ConnectorHealth(ConnectorHealthStatus.NOT_CONFIGURED, "not available")

    # -- Capability execution --

    def execute(self, capability: str, params: dict[str, Any], *, permissions: set[Permission] | None = None) -> dict[str, Any]:
        if capability == "web.crawl_url":
            return self._crawl_url(params)
        elif capability == "web.analyze_page":
            return self._analyze_page(params)
        elif capability == "web.seo_audit":
            return self._seo_audit(params)
        elif capability == "web.extract_content":
            return self._extract_content(params)
        else:
            return {"error": f"unknown capability: {capability}"}

    # -- Operations --

    def _crawl_url(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        if not url:
            return {"error": "url is required"}
        if _crawl4ai_available:
            return self._crawl_in_process(url, params)
        elif self.server_url:
            return self._crawl_remote(url, params)
        return {"error": "crawl4ai not available"}

    def _crawl_in_process(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Crawl using the crawl4ai Python library."""
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

            browser_config = BrowserConfig(headless=True)
            run_config = CrawlerRunConfig(
                word_count_threshold=10,
                exclude_external_links=True,
            )

            import asyncio

            async def _do_crawl() -> dict[str, Any]:
                async with AsyncWebCrawler(config=browser_config) as crawler:
                    result = await crawler.arun(url=url, config=run_config)
                    return {
                        "url": url,
                        "title": result.metadata.get("title", "") if result.metadata else "",
                        "markdown": result.markdown_v2.raw_markdown if hasattr(result, "markdown_v2") and result.markdown_v2 else str(result.markdown) if result.markdown else "",
                        "success": result.success,
                        "links": result.links.get("internal", []) + result.links.get("external", []) if result.links else [],
                        "error": result.error_message if not result.success else None,
                    }

            return asyncio.run(_do_crawl())
        except Exception as exc:  # noqa: BLE001
            logger.exception("Crawl4AI in-process crawl failed")
            return {"error": str(exc), "url": url}

    def _crawl_remote(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """Crawl using a remote crawl4ai server."""
        import json
        from urllib.request import Request, urlopen

        try:
            data = json.dumps({"urls": [url]}).encode("utf-8")
            req = Request(
                f"{self.server_url}/crawl",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                first = result[0] if isinstance(result, list) else result
                return {
                    "url": url,
                    "title": first.get("metadata", {}).get("title", ""),
                    "markdown": first.get("markdown", ""),
                    "success": first.get("success", True),
                    "error": first.get("error_message"),
                }
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc), "url": url}

    def _analyze_page(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        if not url:
            return {"error": "url is required"}
        crawl_result = self._crawl_url(params)
        if crawl_result.get("error"):
            return crawl_result
        markdown = crawl_result.get("markdown", "")
        return {
            "url": url,
            "title": crawl_result.get("title", ""),
            "word_count": len(markdown.split()),
            "has_content": bool(markdown.strip()),
            "links_count": len(crawl_result.get("links", [])),
            "provider": "crawl4ai",
        }

    def _seo_audit(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        if not url:
            return {"error": "url is required"}
        crawl_result = self._crawl_url(params)
        if crawl_result.get("error"):
            return crawl_result

        markdown = crawl_result.get("markdown", "")
        title = crawl_result.get("title", "")
        issues: list[str] = []
        score = 100

        if not title:
            issues.append("Missing page title")
            score -= 20
        if len(title) > 60:
            issues.append("Title too long (>60 chars)")
            score -= 10
        if len(markdown.split()) < 300:
            issues.append("Thin content (<300 words)")
            score -= 15
        if not crawl_result.get("links"):
            issues.append("No internal links found")
            score -= 10

        return {
            "url": url,
            "title": title,
            "word_count": len(markdown.split()),
            "links_count": len(crawl_result.get("links", [])),
            "issues": issues,
            "score": max(0, score),
            "provider": "crawl4ai",
        }

    def _extract_content(self, params: dict[str, Any]) -> dict[str, Any]:
        url = params.get("url", "")
        if not url:
            return {"error": "url is required"}
        crawl_result = self._crawl_url(params)
        if crawl_result.get("error"):
            return crawl_result
        return {
            "url": url,
            "title": crawl_result.get("title", ""),
            "content": crawl_result.get("markdown", ""),
            "provider": "crawl4ai",
        }
