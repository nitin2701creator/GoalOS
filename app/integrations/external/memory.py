"""Memory capability adapter — wraps TencentDB Agent Memory behind GoalOS interfaces.

TencentDB Agent Memory provides long-term semantic memory with vector search.
This adapter builds a clean GoalOS-level memory interface.

In Phase 1, this is a provider-neutral interface. The actual TencentDB
Agent Memory integration will be completed when the service is deployed.

Environment variables:
    GOALOS_MEMORY_BASE_URL  — Memory service URL
    GOALOS_MEMORY_API_KEY   — Memory service API key
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agents.permissions import Permission
from app.integrations.base_connector import BaseConnector
from app.integrations.connector_health import ConnectorHealth, ConnectorHealthStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A single memory record."""

    memory_id: str
    content: str
    entity: str = ""
    memory_type: str = "fact"
    importance: float = 0.5
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    provider: str = "tencentdb"


@dataclass(frozen=True, slots=True)
class RememberRequest:
    """Request to store a memory."""

    content: str
    entity: str = ""
    memory_type: str = "fact"
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RecallRequest:
    """Request to recall memories."""

    query: str
    entity: str = ""
    memory_type: str | None = None
    limit: int = 10


# ---------------------------------------------------------------------------
# Memory Connector
# ---------------------------------------------------------------------------

class MemoryConnector(BaseConnector):
    """GoalOS connector for long-term memory service.

    Provides remember/recall/search/forget operations behind a clean
    GoalOS interface. Phase 1 is the interface definition; the actual
    TencentDB Agent Memory backend will be wired when the service is
    deployed on the VPS.
    """

    required_env_vars: tuple[str, ...] = ()

    CAPABILITY_PERMISSIONS: dict[str, Permission] = {
        "memory.remember": Permission.READ_SOCIAL,
        "memory.recall": Permission.READ_SOCIAL,
        "memory.search": Permission.READ_SOCIAL,
        "memory.forget": Permission.READ_SOCIAL,
        "memory.health": Permission.READ_SOCIAL,
    }

    def __init__(self) -> None:
        super().__init__(
            name="memory",
            description="Long-term semantic memory adapter (TencentDB Agent Memory)",
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
            return False, "Memory service not deployed — GOALOS_MEMORY_BASE_URL not set"
        return True, "available"

    @property
    def base_url(self) -> str:
        return os.environ.get("GOALOS_MEMORY_BASE_URL", "").rstrip("/")

    @property
    def api_key(self) -> str:
        return os.environ.get("GOALOS_MEMORY_API_KEY", "")

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
                "GOALOS_MEMORY_BASE_URL not set — memory service not deployed",
            ))

    def disconnect(self) -> None:
        self._set_health(ConnectorHealth(ConnectorHealthStatus.DISCONNECTED, "disconnected"))

    def health_check(self) -> ConnectorHealth:
        if not self.is_configured:
            return ConnectorHealth(
                ConnectorHealthStatus.NOT_CONFIGURED,
                "memory service not deployed — interface ready, backend pending",
            )
        try:
            result = self._api_get("/health")
            if result.get("status") == "ok":
                return ConnectorHealth(ConnectorHealthStatus.HEALTHY, "memory service healthy")
            return ConnectorHealth(ConnectorHealthStatus.DEGRADED, f"unexpected: {result}")
        except Exception as exc:  # noqa: BLE001
            return ConnectorHealth(ConnectorHealthStatus.UNHEALTHY, f"health check failed: {exc}")

    # -- Capability execution --

    def execute(self, capability: str, params: dict[str, Any], *, permissions: set[Permission] | None = None) -> dict[str, Any]:
        if capability == "memory.remember":
            return self._remember(params)
        elif capability == "memory.recall":
            return self._recall(params)
        elif capability == "memory.search":
            return self._search(params)
        elif capability == "memory.forget":
            return self._forget(params)
        elif capability == "memory.health":
            health = self.health_check()
            return {"status": health.status.value, "message": health.message}
        else:
            return {"error": f"unknown capability: {capability}"}

    # -- Operations --

    def _remember(self, params: dict[str, Any]) -> dict[str, Any]:
        content = params.get("content", "")
        if not content:
            return {"error": "content is required"}
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: memory service not deployed"}
        try:
            result = self._api_post("/api/v1/memories", {
                "content": content,
                "entity": params.get("entity", ""),
                "memory_type": params.get("memory_type", "fact"),
                "importance": params.get("importance", 0.5),
                "metadata": params.get("metadata", {}),
            })
            return {"success": True, "memory_id": result.get("id", ""), "provider": "tencentdb"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def _recall(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: memory service not deployed"}
        try:
            result = self._api_post("/api/v1/memories/recall", {
                "query": query,
                "entity": params.get("entity", ""),
                "memory_type": params.get("memory_type"),
                "limit": params.get("limit", 10),
            })
            return {"memories": result.get("memories", []), "count": len(result.get("memories", [])), "provider": "tencentdb"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: memory service not deployed"}
        try:
            result = self._api_post("/api/v1/memories/search", {
                "query": query,
                "limit": params.get("limit", 10),
            })
            return {"results": result.get("results", []), "count": len(result.get("results", [])), "provider": "tencentdb"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    def _forget(self, params: dict[str, Any]) -> dict[str, Any]:
        memory_id = params.get("memory_id", "")
        if not memory_id:
            return {"error": "memory_id is required"}
        if not self.is_configured:
            return {"error": "INTEGRATION_NOT_CONFIGURED: memory service not deployed"}
        try:
            self._api_delete(f"/api/v1/memories/{memory_id}")
            return {"success": True, "memory_id": memory_id, "provider": "tencentdb"}
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    # -- HTTP helpers --

    def _api_get(self, path: str) -> Any:
        return self._request("GET", path)

    def _api_post(self, path: str, data: dict[str, Any]) -> Any:
        return self._request("POST", path, data)

    def _api_delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = json.dumps(data).encode("utf-8") if data else None
        req = Request(url, data=body, headers=headers, method=method)

        try:
            with urlopen(req, timeout=30) as resp:
                response_body = resp.read().decode("utf-8")
                return json.loads(response_body)
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Memory API error {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Memory connection failed: {exc.reason}") from exc
