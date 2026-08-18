"""n8n workflow automation integration (public REST API).

``N8NConnector`` talks to n8n's public REST API (``/api/v1``) over the
shared HTTP client with the ``X-N8N-API-KEY`` header from environment
configuration. The base URL is fully configurable so it works against any
n8n deployment (Docker, desktop, cloud).

Configuration accepts ``N8N_BASE_URL``/``N8N_API_KEY`` with the legacy
``GOALOS_N8N_BASE_URL``/``GOALOS_N8N_API_KEY`` names as fallbacks.

Capabilities:

- ``n8n.health`` — configuration readiness (no network call).
- ``n8n.list_workflows`` — paginated workflow list.
- ``n8n.get_workflow`` — one workflow by id.
- ``n8n.run_workflow`` — trigger one workflow execution via
  ``POST /api/v1/workflows/{id}/run`` (the public-API equivalent of
  triggering the workflow's manual/webhook trigger), then fetch and return
  the resulting execution.
- ``n8n.get_execution`` — one execution by id.

Honesty contract:

- Missing base URL/API key reports ``Not Configured`` — never a fake
  success.
- HTTP 401/403 maps to :class:`AuthenticationError` (invalid/expired API
  key), distinct from other failures.
- HTTP 429 maps to :class:`RateLimitError`.
- A workflow execution that finishes with status error/failed/crashed
  raises :class:`ConnectorError` — a failed workflow is never reported as
  a success.
- Other non-success statuses and malformed responses raise structured
  errors so the execution runtime persists a real failure.
- Reads require ``READ_AUTOMATION``; ``n8n.run_workflow`` requires
  ``EXECUTE_AUTOMATION`` (a dangerous permission never granted implicitly).
- API keys are never logged and never included in execution output.
"""

from __future__ import annotations

import json
import time
from typing import Any, ClassVar
from urllib.parse import urljoin

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

#: Read-only n8n capabilities (require READ_AUTOMATION).
_READ_CAPABILITIES = frozenset(
    {
        "n8n.health",
        "n8n.list_workflows",
        "n8n.get_workflow",
        "n8n.get_execution",
    }
)

#: How long to wait between execution-result polls after a run (seconds).
_POLL_INTERVAL_SECONDS = 0.5
#: Maximum number of execution-result polls after a run.
_MAX_POLL_ATTEMPTS = 5
#: Maximum number of node results returned in a run summary.
_MAX_NODE_RESULTS = 5

#: Execution statuses that mean the workflow itself failed.
_FAILED_EXECUTION_STATUSES = frozenset({"error", "failed", "crashed"})


class N8NConnector(IntegrationConnector):
    """n8n workflow-automation connector (public REST API)."""

    required_env_vars: tuple[str, ...] = ("N8N_BASE_URL", "N8N_API_KEY")
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        capability: (
            Permission.READ_AUTOMATION
            if capability in _READ_CAPABILITIES
            else Permission.EXECUTE_AUTOMATION
        )
        for capability in (
            "n8n.health",
            "n8n.list_workflows",
            "n8n.get_workflow",
            "n8n.run_workflow",
            "n8n.get_execution",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            name="n8n",
            description="n8n workflow automation (public REST API)",
        )
        self.client = client or HttpClient()
        base = (
            base_url
            or self._env("N8N_BASE_URL")
            or self._env("GOALOS_N8N_BASE_URL")
            or ""
        ).rstrip("/")
        # Accept a bare origin (https://n8n.example.com) or an explicit
        # /api/v1 root; the public API always lives under /api/v1.
        self.base_url = base if base.endswith("/api/v1") else f"{base}/api/v1"
        self.api_key = (
            api_key
            or self._env("N8N_API_KEY")
            or self._env("GOALOS_N8N_API_KEY")
            or ""
        )

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "n8n.health",
            "n8n.list_workflows",
            "n8n.get_workflow",
            "n8n.run_workflow",
            "n8n.get_execution",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing: list[str] = []
        if not self.base_url or not self.base_url.startswith(("http://", "https://")):
            missing.append("N8N_BASE_URL (or GOALOS_N8N_BASE_URL)")
        if not self.api_key:
            missing.append("N8N_API_KEY (or GOALOS_N8N_API_KEY)")
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "n8n.health":
            return self._health()
        if capability == "n8n.list_workflows":
            return self._list_workflows(params)
        if capability == "n8n.get_workflow":
            return self._get_workflow(params)
        if capability == "n8n.run_workflow":
            return self._run_workflow(params)
        if capability == "n8n.get_execution":
            return self._get_execution(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _list_workflows(self, params: dict[str, Any]) -> dict[str, Any]:
        """List workflows with optional limit/active/name filters."""
        query: dict[str, Any] = {}
        if params.get("limit"):
            query["limit"] = int(params["limit"])
        if params.get("active") is not None:
            query["active"] = "true" if params["active"] else "false"
        if params.get("name"):
            query["name"] = params["name"]
        payload = self._decode(
            self._fetch("GET", self._url("workflows"), headers=self._headers(), params=query),
            path="/api/v1/workflows",
        )
        items = payload.get("data")
        if not isinstance(items, list):
            raise ConnectorError(
                "invalid response from n8n at /api/v1/workflows: "
                "expected a JSON object with a 'data' array"
            )
        return {
            "total": len(items),
            "next_cursor": payload.get("nextCursor"),
            "items": items,
        }

    def _get_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch one workflow by id."""
        workflow_id = params.get("id") or params.get("workflow_id")
        if not workflow_id:
            raise ValueError("id is required for n8n.get_workflow")
        payload = self._decode(
            self._fetch(
                "GET",
                self._url(f"workflows/{workflow_id}"),
                headers=self._headers(),
            ),
            path=f"/api/v1/workflows/{workflow_id}",
        )
        return {"workflow": payload}

    def _run_workflow(self, params: dict[str, Any]) -> dict[str, Any]:
        """Trigger one workflow execution and return its result.

        ``POST /api/v1/workflows/{id}/run`` starts the workflow's manual
        trigger with the optional ``payload`` as ``manualTriggerPayload``.
        The resulting execution is then fetched (with a short bounded poll)
        and summarized — never fabricated. A workflow that finishes with an
        error status raises instead of reporting success.
        """
        workflow_id = params.get("id") or params.get("workflow_id")
        if not workflow_id:
            raise ValueError("id is required for n8n.run_workflow")
        body: dict[str, Any] = {}
        if params.get("payload") is not None:
            body["manualTriggerPayload"] = params["payload"]
        for key in ("startNodes", "destinationNode"):
            if params.get(key) is not None:
                body[key] = params[key]
        response = self._fetch(
            "POST",
            self._url(f"workflows/{workflow_id}/run"),
            headers={**self._headers(), "Content-Type": "application/json"},
            body=json.dumps(body).encode() if body else None,
        )
        payload = self._decode(
            response,
            path=f"/api/v1/workflows/{workflow_id}/run",
        )
        execution_id = payload.get("executionId") or payload.get("execution_id")
        if not execution_id:
            raise ConnectorError(
                "invalid response from n8n at "
                f"/api/v1/workflows/{workflow_id}/run: "
                "response did not include an executionId"
            )
        return self._execution_result(str(execution_id), workflow_id=workflow_id)

    def _get_execution(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch one execution by id."""
        execution_id = params.get("id") or params.get("execution_id")
        if not execution_id:
            raise ValueError("id is required for n8n.get_execution")
        return self._execution_result(str(execution_id))

    def _execution_result(
        self,
        execution_id: str,
        *,
        workflow_id: str | None = None,
    ) -> dict[str, Any]:
        """Fetch an execution, polling briefly until finished."""
        attempts = 0
        while True:
            payload = self._decode(
                self._fetch(
                    "GET",
                    self._url(f"executions/{execution_id}"),
                    headers=self._headers(),
                ),
                path=f"/api/v1/executions/{execution_id}",
            )
            finished = bool(payload.get("finished"))
            status = payload.get("status") or ("success" if finished else "running")
            if finished and status in _FAILED_EXECUTION_STATUSES:
                failure = self._execution_failure(payload, execution_id)
                raise ConnectorError(
                    "n8n workflow execution failed: "
                    f"execution {execution_id} finished with status '{status}'"
                    + (f" at node '{failure}'" if failure else "")
                )
            result = self._summarize_execution(payload, execution_id, workflow_id)
            attempts += 1
            if finished or attempts >= _MAX_POLL_ATTEMPTS:
                return result
            time.sleep(_POLL_INTERVAL_SECONDS)

    @staticmethod
    def _summarize_execution(
        payload: dict[str, Any],
        execution_id: str,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        """Reduce an n8n execution payload to a bounded structured summary."""
        finished = bool(payload.get("finished"))
        status = payload.get("status") or ("success" if finished else "running")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        result_data = data.get("resultData") if isinstance(data.get("resultData"), dict) else {}
        last_node = result_data.get("lastNodeExecuted")
        run_data = result_data.get("runData") if isinstance(result_data.get("runData"), dict) else {}
        nodes: list[dict[str, Any]] = []
        for node_name, outputs in run_data.items():
            if len(nodes) >= _MAX_NODE_RESULTS:
                break
            nodes.append({"node": node_name, "output": N8NConnector._node_output(outputs)})
        summary: dict[str, Any] = {
            "execution_id": str(payload.get("id") or execution_id),
            "finished": finished,
            "status": status,
            "last_node": last_node,
        }
        if workflow_id is not None:
            summary["workflow_id"] = workflow_id
        summary["node_outputs"] = nodes
        return summary

    @staticmethod
    def _node_output(outputs: Any) -> Any:
        """Extract the first JSON item from an n8n runData entry.

        runData maps node name -> {output_type: [[{json, error}, ...], ...]};
        only the first branch's first item is returned, bounded by the HTTP
        body cap already applied by the shared client.
        """
        try:
            branches = outputs.get("main") if isinstance(outputs, dict) else outputs
            if not isinstance(branches, list) or not branches:
                return None
            first_branch = branches[0]
            if not isinstance(first_branch, list) or not first_branch:
                return None
            item = first_branch[0]
            if isinstance(item, dict):
                return item.get("json")
        except (IndexError, TypeError, AttributeError):
            return None
        return None

    @staticmethod
    def _execution_failure(payload: dict[str, Any], execution_id: str) -> str | None:
        """Return the first failing node name for a failed execution, if any."""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        result_data = data.get("resultData") if isinstance(data.get("resultData"), dict) else {}
        run_data = result_data.get("runData") if isinstance(result_data.get("runData"), dict) else {}
        for node_name, outputs in run_data.items():
            branches = outputs.get("main") if isinstance(outputs, dict) else outputs
            if not isinstance(branches, list):
                continue
            for branch in branches:
                if not isinstance(branch, list):
                    continue
                for item in branch:
                    if isinstance(item, dict) and item.get("error"):
                        return node_name
        return result_data.get("lastNodeExecuted")

    def _health(self) -> dict[str, Any]:
        """Report configuration health without touching the network."""
        status, message = self._configuration_status()
        return {
            "integration": "n8n",
            "status": status.value,
            "configured": status.value == "Healthy",
            "message": message,
        }

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------
    def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a request, mapping transport failures to distinct errors."""
        try:
            return self.client.fetch(url, method=method, headers=headers, body=body, params=params)
        except HttpStatusError as exc:
            status = int(exc.status)
            if status in (401, 403):
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: HTTP {status} from n8n at {exc.url} "
                    "(check N8N_API_KEY)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: n8n returned HTTP 429 at {exc.url} "
                    "(reduce workflow trigger frequency)"
                ) from exc
            raise ConnectorError(f"n8n API error: HTTP {status} at {exc.url}") from exc

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        return {"X-N8N-API-KEY": self.api_key}

    def _decode(self, response: Any, *, path: str) -> dict[str, Any]:
        """Parse an n8n response, mapping status/JSON failures distinctly."""
        status = int(getattr(response, "status", 200) or 200)
        if status in (401, 403):
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: HTTP {status} from n8n at {path} "
                "(check N8N_API_KEY)"
            )
        if status == 429:
            raise RateLimitError(
                f"RATE_LIMITED: n8n returned HTTP 429 at {path} "
                "(reduce workflow trigger frequency)"
            )
        if status >= 400:
            message = self._error_message(response.text)
            raise ConnectorError(f"n8n API error: HTTP {status} at {path}: {message}")
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from n8n at {path}: response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from n8n at {path}: expected a JSON object"
            )
        return payload

    @staticmethod
    def _error_message(text: str) -> str:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text[:500]
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])[:500]
        return text[:500]
