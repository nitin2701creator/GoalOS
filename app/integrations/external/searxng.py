"""Search capability adapter — wraps SearXNG behind GoalOS interfaces.

SearXNG is a privacy-respecting metasearch engine. This adapter connects
to a running SearXNG instance via its JSON API.

Environment variables:
    GOALOS_SEARXNG_BASE_URL — SearXNG instance URL (e.g. http://localhost:8888)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.agents.permissions import Permission
from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SearchRequest:
    """Search query request."""

    query: str
    categories: list[str] = field(default_factory=lambda: ["general"])
    language: str = "en"
    max_results: int = 10


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Single search result."""

    title: str
    url: str
    content: str
    engine: str = ""
    score: float = 0.0


@dataclass(frozen=True, slots=True)
class SearchResponse:
    """Search results response."""

    query: str
    results: list[SearchResult]
    total: int
    provider: str = "searxng"


# ---------------------------------------------------------------------------
# SearXNG Connector
# ---------------------------------------------------------------------------

class SearXNGConnector(BaseConnector):
    """GoalOS connector for SearXNG search engine."""

    required_env_vars = ("GOALOS_SEARXNG_BASE_URL",)

    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "search.web": Permission.READ_WEBSITE,
        "search.news": Permission.READ_WEBSITE,
        "search.images": Permission.READ_WEBSITE,
    }

    def __init__(self) -> None:
        super().__init__(
            name="searxng",
            description="SearXNG privacy-respecting search engine adapter",
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
            return False, "SearXNG not configured — GOALOS_SEARXNG_BASE_URL not set"
        return True, "available"

    @property
    def base_url(self) -> str:
        return os.environ.get("GOALOS_SEARXNG_BASE_URL", "").rstrip("/")

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url)

    # -- Lifecycle --

    def connect(self) -> None:
        if self.is_configured:
            self._set_health(ConnectorHealth(ConnectorHealthStatus.HEALTHY, "configured"))
        else:
            self._set_health(ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "GOALOS_SEARXNG_BASE_URL not set",
            ))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "disconnected"))

    def health_check(self) -> ConnectorHealth:
        if not self.is_configured:
            return ConnectorHealth(ConnectorHealthStatus.NOT_CONFIGURED, "not configured")
        try:
            url = f"{self.base_url}/healthz"
            req = Request(url, method="GET")
            with urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "searxng healthy")
        except Exception:  # noqa: BLE001
            pass
        # healthz might not exist; try a simple search
        try:
            result = self._search("test", max_results=1)
            return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "search responds")
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(ConnectorHealthStatus.UNHEALTHY, f"search failed: {exc}")

    # -- Capability execution --

    def execute(self, capability: str, params: dict[str, Any], *, permissions: set[Permission] | None = None) -> dict[str, Any]:
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: GOALOS_SEARXNG_BASE_URL not set"}
        if capability in ("search.web", "search.news", "search.images"):
            return self._do_search(params, capability)
        else:
            return {"error": f"unknown capability: {capability}"}

    # -- Search --

    def _do_search(self, params: dict[str, Any], capability: str) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}

        categories = params.get("categories", [])
        if not categories:
            if capability == "search.news":
                categories = ["news"]
            elif capability == "search.images":
                categories = ["images"]
            else:
                categories = ["general"]

        max_results = params.get("max_results", 10)
        language = params.get("language", "en")

        try:
            results = self._search(query, categories=categories, language=language, max_results=max_results)
            return {
                "query": query,
                "results": results,
                "total": len(results),
                "provider": "searxng",
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("SearXNG search failed")
            return {"error": str(exc), "query": query}

    def _search(
        self,
        query: str,
        categories: list[str] | None = None,
        language: str = "en",
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "language": language,
        }
        if categories:
            params["categories"] = ",".join(categories)

        url = f"{self.base_url}/search?{urlencode(params)}"
        req = Request(url, method="GET", headers={"Accept": "application/json"})

        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = []
        for item in data.get("results", [])[:max_results]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "engine": item.get("engine", ""),
                "score": item.get("score", 0.0),
            })
        return results
