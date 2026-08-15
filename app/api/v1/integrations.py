"""Integration registry and execution API endpoints.

Integrations are executable boundaries over the connector registry: each
one can be listed, inspected, health-tested, enabled/disabled, and
executed (one capability at a time, fully persisted as a runtime
execution record). Execution is honest — an unconfigured integration
reports ``INTEGRATION_NOT_CONFIGURED``, a disabled one ``DISABLED``, an
unknown one ``INTEGRATION_NOT_FOUND``; never a fabricated success and
never a leaked secret.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.db.session import get_db
from app.schemas.integration import (
    IntegrationExecuteRequest,
    IntegrationExecuteResponse,
    IntegrationSummaryResponse,
    IntegrationTestResponse,
    IntegrationUpdateRequest,
)
from app.services.integration_service import IntegrationService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> IntegrationService:
    """Compose the integration service per request (existing conventions)."""
    return IntegrationService(db)


@router.get("")
def list_integrations(service: IntegrationService = Depends(_get_service)):
    """List every registered integration and its configuration state.

    ``sync`` first makes the persisted registry match the connector
    registry (idempotent, preserves operator-set enabled state). Only
    configuration *state* and env var *names* are exposed — never
    credentials or values.
    """
    service.sync()
    integrations = service.list()
    return {"integrations": integrations, "total": len(integrations)}


@router.get("/{name}", response_model=IntegrationSummaryResponse)
def get_integration(name: str, service: IntegrationService = Depends(_get_service)):
    """Return one integration with its live health snapshot."""
    service.sync()
    result = service.get(name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    return result


@router.post("/{name}/test", response_model=IntegrationTestResponse)
def test_integration(name: str, service: IntegrationService = Depends(_get_service)):
    """Run the health/test operation and cache the health snapshot."""
    service.sync()
    result = service.test(name)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    return result


@router.post("/{name}/execute", response_model=IntegrationExecuteResponse)
def execute_integration(
    name: str,
    request: IntegrationExecuteRequest,
    service: IntegrationService = Depends(_get_service),
):
    """Execute one capability of an integration, fully persisted.

    The run is recorded in ``runtime_executions`` (the same audit trail
    as the execution runtime) and returned with the structured outcome.
    """
    service.sync()
    return service.execute(
        name,
        request.capability,
        request.params,
        request.permissions,
    )


@router.get("/{name}/executions")
def integration_executions(
    name: str,
    capability: str | None = None,
    service: IntegrationService = Depends(_get_service),
):
    """Return the persisted execution history for one integration."""
    service.sync()
    if service.get(name) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    executions = service.execution_history(name, capability=capability)
    return {"integration": name, "executions": executions, "total": len(executions)}


@router.patch("/{name}", response_model=IntegrationSummaryResponse)
def update_integration(
    name: str,
    request: IntegrationUpdateRequest,
    service: IntegrationService = Depends(_get_service),
):
    """Enable/disable an integration (operator control)."""
    service.sync()
    result = service.set_enabled(name, request.enabled)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found"
        )
    return result
