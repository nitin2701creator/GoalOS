"""GoalOS integration execution foundation.

The service turns the connector registry into a persisted, executable
integration registry. One :class:`Integration` row per registered
connector captures name, functional type, description, enabled/disabled
state, exposed capabilities, and the *names* of the configuring
environment variables (never their values).

Operations:

- ``sync``: idempotently persist every connector in the registry
  (preserving operator-set enabled state across restarts).
- ``list`` / ``get``: registry views merged with live connector health.
- ``set_enabled``: operator enable/disable — a disabled integration never
  executes.
- ``test``: health/test operation — validates configuration through the
  existing connector lifecycle and caches the health snapshot.
- ``execute``: dispatch one capability through the existing connector
  (the same execution path agents and skills use) and persist the run as
  a ``runtime_executions`` record — input, output, error, stable error
  code, timestamps. Failures are honest and never fabricated:

  - unknown integration → ``INTEGRATION_NOT_FOUND``
  - disabled integration → ``DISABLED``
  - unconfigured/unsupported capability → ``INTEGRATION_NOT_CONFIGURED``
  - missing permission → ``PERMISSION_DENIED``
  - authentication failure → ``AUTHENTICATION_FAILED``
  - rate limiting → ``RATE_LIMITED``
  - other connector/transport errors → ``EXECUTION_FAILED``

- ``execution_history``: the persisted audit trail for one integration.

No secret is ever read into the database or returned by the API — only
configuration *state* and env var *names*.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agents.permissions import Permission
from app.db.models.integration import Integration
from app.db.models.runtime_execution import RuntimeExecution, RuntimeExecutionStatus
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.factory import build_default_registry, integration_type_for
from app.repositories.integration_repository import IntegrationRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.schemas.integration import (
    IntegrationExecuteResponse,
    IntegrationSummaryResponse,
    IntegrationTestResponse,
)
from app.schemas.runtime_execution import RuntimeExecutionResponse

logger = logging.getLogger(__name__)


class IntegrationErrorCode:
    """Stable machine-readable failure codes for integration execution."""

    INTEGRATION_NOT_FOUND = "INTEGRATION_NOT_FOUND"
    INTEGRATION_NOT_CONFIGURED = "INTEGRATION_NOT_CONFIGURED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    DISABLED = "DISABLED"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class IntegrationService:
    """Persisted integration registry and execution boundary."""

    def __init__(
        self,
        db: Session,
        registry: ConnectorRegistry | None = None,
        *,
        client: Any = None,
    ) -> None:
        self.db = db
        self.repository = IntegrationRepository(db)
        self.runtime_repository = RuntimeExecutionRepository(db)
        self.registry = registry or build_default_registry(session=db, client=client)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    def sync(self) -> list[IntegrationSummaryResponse]:
        """Idempotently persist every registered connector as an integration.

        Preserves the operator-set ``enabled`` state across restarts;
        description/capabilities/config references are refreshed from the
        connector so the registry never goes stale.
        """
        for name in self.registry.list_connectors():
            connector = self.registry.get_connector(name)
            if connector is None:  # pragma: no cover - registry invariant
                continue
            values: dict[str, Any] = {
                "name": connector.name,
                "integration_type": integration_type_for(connector.name),
                "description": connector.description,
                "capabilities": list(connector.get_capabilities()),
                "required_env_vars": list(
                    getattr(connector, "required_env_vars", ()) or ()
                ),
            }
            row = self.repository.get_by_name(connector.name)
            if row is None:
                self.repository.create({**values, "enabled": True})
            else:
                self.repository.update(row, values)
        return self.list()

    def list(self) -> list[dict[str, Any]]:
        """List the persisted registry merged with live connector health."""
        summaries: list[dict[str, Any]] = []
        for row in self.repository.list():
            summaries.append(self._summary(row))
        return summaries

    def get(self, name: str) -> dict[str, Any] | None:
        """Return one integration with live health, or ``None``."""
        row = self.repository.get_by_name(name)
        if row is None:
            return None
        return self._summary(row)

    def set_enabled(self, name: str, enabled: bool) -> dict[str, Any] | None:
        """Enable/disable an integration (operator control)."""
        row = self.repository.get_by_name(name)
        if row is None:
            return None
        self.repository.update(row, {"enabled": bool(enabled)})
        return self._summary(row)

    # ------------------------------------------------------------------
    # Health / test
    # ------------------------------------------------------------------
    def test(self, name: str) -> IntegrationTestResponse | None:
        """Run the health/test operation and cache the health snapshot.

        Uses the existing connector lifecycle (``connect`` validates
        configuration, ``health_check`` reports readiness) — no network
        round-trip is fabricated, and nothing is reported healthy when
        required configuration is absent.
        """
        connector = self.registry.get_connector(name)
        row = self.repository.get_by_name(name)
        if connector is None or row is None:
            return None
        connector.connect()
        health = connector.health_check()
        checked_at = datetime.now(timezone.utc)
        self.repository.update(
            row,
            {
                "last_health_status": health.status.value,
                "last_health_message": health.message,
                "last_checked_at": checked_at,
            },
        )
        return IntegrationTestResponse(
            integration=name,
            status=health.status.value,
            message=health.message,
            last_checked_at=checked_at,
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def execute(
        self,
        integration: str,
        capability: str,
        params: dict[str, Any] | None = None,
        permissions: set[Permission] | list[Permission] | None = None,
    ) -> IntegrationExecuteResponse:
        """Execute one integration capability, fully persisted.

        The run is recorded in ``runtime_executions`` (the same audit
        trail the execution runtime uses) with the integration name in
        ``provider``. Success and every failure mode return a structured
        response — never a fabricated result and never a leaked secret.
        """
        granted = set(permissions or ())
        row = self.repository.get_by_name(integration)
        connector = self.registry.get_connector(integration)

        if row is None or connector is None:
            return self._reject(
                integration,
                capability,
                params,
                granted,
                "integration is not registered",
                IntegrationErrorCode.INTEGRATION_NOT_FOUND,
                status="INTEGRATION_NOT_FOUND",
            )
        if not row.enabled:
            return self._reject(
                integration,
                capability,
                params,
                granted,
                "integration is disabled",
                IntegrationErrorCode.DISABLED,
                status="DISABLED",
            )

        available, reason = connector.capability_available(capability)
        required_permission = getattr(connector, "CAPABILITY_PERMISSIONS", {}).get(
            capability
        )
        if not available:
            return self._reject(
                integration,
                capability,
                params,
                granted,
                f"INTEGRATION_NOT_CONFIGURED: {reason}",
                IntegrationErrorCode.INTEGRATION_NOT_CONFIGURED,
                status="INTEGRATION_NOT_CONFIGURED",
            )
        if required_permission is not None and required_permission not in granted:
            return self._reject(
                integration,
                capability,
                params,
                granted,
                f"capability '{capability}' requires permission "
                f"'{required_permission.value}', which was not granted",
                IntegrationErrorCode.PERMISSION_DENIED,
                status="PERMISSION_DENIED",
            )

        execution = self.runtime_repository.create(
            {
                "workflow_id": None,
                "capability": capability,
                "status": RuntimeExecutionStatus.PENDING,
                "input": dict(params or {}),
                "provider": integration,
                "permissions_required": (
                    [required_permission.value]
                    if required_permission is not None
                    else []
                ),
                "execution_metadata": {
                    "integration": integration,
                    "integration_type": row.integration_type,
                    "source": "integration_api",
                    "granted_permissions": sorted(
                        permission.value for permission in granted
                    ),
                },
            }
        )
        execution = self.runtime_repository.update(
            execution,
            {"status": RuntimeExecutionStatus.RUNNING, "started_at": datetime.now(timezone.utc)},
        )

        try:
            result = connector.execute(capability, dict(params or {}), permissions=granted)
        except AuthenticationError as exc:
            return self._finish(execution, exc, "AUTHENTICATION_FAILED", row)
        except RateLimitError as exc:
            return self._finish(execution, exc, "RATE_LIMITED", row)
        except PermissionDeniedError as exc:
            return self._finish(execution, exc, "PERMISSION_DENIED", row)
        except CapabilityUnavailableError as exc:
            return self._finish(execution, exc, "INTEGRATION_NOT_CONFIGURED", row)
        except ConnectorError as exc:
            return self._finish(execution, exc, "EXECUTION_FAILED", row)
        except Exception as exc:  # noqa: BLE001 - execution must return structured results
            logger.warning(
                "integration execution of '%s' via '%s' crashed: %s",
                capability,
                integration,
                exc,
            )
            return self._finish(execution, exc, "EXECUTION_FAILED", row)

        if isinstance(result, dict) and result.get("error"):
            return self._finish(
                execution,
                RuntimeError(str(result["error"])),
                "EXECUTION_FAILED",
                row,
            )
        return self._finish(
            execution,
            None,
            None,
            row,
            output=result if isinstance(result, dict) else {"result": result},
        )

    def execution_history(
        self,
        integration: str,
        capability: str | None = None,
    ) -> list[RuntimeExecutionResponse]:
        """Return the persisted execution trail for one integration."""
        executions = self.runtime_repository.list_by_provider(integration)
        if capability is not None:
            executions = [
                execution for execution in executions if execution.capability == capability
            ]
        return [RuntimeExecutionResponse.model_validate(execution) for execution in executions]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _summary(self, row: Integration) -> dict[str, Any]:
        """Merge a persisted row with live connector health."""
        connector = self.registry.get_connector(row.name)
        registered = connector is not None
        status: str | None = row.last_health_status
        message: str | None = row.last_health_message
        if connector is not None:
            health = connector.health_check()
            status = health.status.value
            message = health.message
        summary = IntegrationSummaryResponse.model_validate(row).model_dump(
            mode="json"
        )
        summary["registered"] = registered
        summary["status"] = status
        summary["message"] = message
        return summary

    def _reject(
        self,
        integration: str,
        capability: str,
        params: dict[str, Any] | None,
        granted: set[Permission],
        error: str,
        code: str,
        *,
        status: str,
    ) -> IntegrationExecuteResponse:
        """Persist a refused execution (no dispatch) with the honest reason."""
        execution = self.runtime_repository.create(
            {
                "workflow_id": None,
                "capability": capability,
                "status": RuntimeExecutionStatus.FAILED,
                "input": dict(params or {}),
                "output": None,
                "error": error,
                "error_code": code,
                "provider": integration,
                "permissions_required": [],
                "execution_metadata": {
                    "integration": integration,
                    "source": "integration_api",
                    "granted_permissions": sorted(
                        permission.value for permission in granted
                    ),
                    "rejected": True,
                },
                "completed_at": datetime.now(timezone.utc),
            }
        )
        return IntegrationExecuteResponse(
            integration=integration,
            capability=capability,
            status=status,  # type: ignore[arg-type]
            error_code=code,
            error=error,
            execution=RuntimeExecutionResponse.model_validate(execution),
        )

    def _finish(
        self,
        execution: RuntimeExecution,
        error: Exception | None,
        code: str | None,
        row: Integration,
        *,
        output: dict[str, Any] | None = None,
    ) -> IntegrationExecuteResponse:
        """Persist the final state of a dispatched execution."""
        if error is None:
            execution = self.runtime_repository.update(
                execution,
                {
                    "status": RuntimeExecutionStatus.SUCCEEDED,
                    "output": output,
                    "error": None,
                    "error_code": None,
                    "completed_at": datetime.now(timezone.utc),
                },
            )
            return IntegrationExecuteResponse(
                integration=row.name,
                capability=execution.capability,
                status="OK",
                result=output,
                execution=RuntimeExecutionResponse.model_validate(execution),
            )
        execution = self.runtime_repository.update(
            execution,
            {
                "status": RuntimeExecutionStatus.FAILED,
                "output": output,
                "error": str(error),
                "error_code": code or IntegrationErrorCode.EXECUTION_FAILED,
                "completed_at": datetime.now(timezone.utc),
            },
        )
        status_map: dict[str, str] = {
            IntegrationErrorCode.INTEGRATION_NOT_FOUND: "INTEGRATION_NOT_FOUND",
            IntegrationErrorCode.INTEGRATION_NOT_CONFIGURED: "INTEGRATION_NOT_CONFIGURED",
            IntegrationErrorCode.PERMISSION_DENIED: "PERMISSION_DENIED",
            IntegrationErrorCode.DISABLED: "DISABLED",
            IntegrationErrorCode.AUTHENTICATION_FAILED: "AUTHENTICATION_FAILED",
            IntegrationErrorCode.RATE_LIMITED: "RATE_LIMITED",
        }
        return IntegrationExecuteResponse(
            integration=row.name,
            capability=execution.capability,
            status=status_map.get(  # type: ignore[arg-type]
                execution.error_code or "", "ERROR"
            ),
            error_code=execution.error_code,
            error=str(error),
            execution=RuntimeExecutionResponse.model_validate(execution),
        )
